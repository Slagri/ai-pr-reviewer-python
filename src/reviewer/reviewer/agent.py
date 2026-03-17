"""Core AI review agent with Azure OpenAI tool-use loop.

The agent sends the PR context to GPT-5.4, executes any tool calls,
feeds results back, and loops until it produces a final JSON review.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

import structlog
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
    ChatCompletionUserMessageParam,
)

from reviewer.exceptions import AgentError
from reviewer.models import Category, Finding, Review, Severity, TokenUsage

if TYPE_CHECKING:
    from openai import AsyncAzureOpenAI
from reviewer.reviewer.tools import TOOL_DEFINITIONS, ToolExecutor
from reviewer.reviewer.trace import AgentTrace

logger = structlog.get_logger()


def _parse_review_json(content: str) -> dict[str, Any]:
    """Extract and parse JSON from the agent's final response.

    Handles JSON wrapped in ```json code blocks or bare JSON.
    """
    text = content.strip()

    # Strip markdown code block wrapper
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    parsed: dict[str, Any] = json.loads(text)
    return parsed


def _parse_findings(data: dict[str, Any]) -> tuple[Finding, ...]:
    """Parse findings from the agent's JSON response into Finding models."""
    raw_findings = data.get("findings", [])
    findings: list[Finding] = []

    for f in raw_findings:
        try:
            findings.append(
                Finding(
                    path=f["path"],
                    line=f.get("line", 0),
                    severity=Severity(f.get("severity", "info")),
                    category=Category(f.get("category", "maintainability")),
                    message=f.get("message", ""),
                    suggestion=f.get("suggestion", ""),
                )
            )
        except (KeyError, ValueError) as exc:
            logger.warning("skipping malformed finding", error=str(exc), raw=f)

    return tuple(findings)


async def run_review_agent(
    *,
    client: AsyncAzureOpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    tool_executor: ToolExecutor,
    max_iterations: int = 10,
    cancel_event: asyncio.Event | None = None,
) -> tuple[dict[str, Any], AgentTrace]:
    """Run the AI review agent's tool-use loop.

    Returns (parsed_review_dict, trace).

    Flow:
    1. Send system + user message with tool definitions
    2. If finish_reason == "tool_calls": execute tools, append results, loop
    3. If finish_reason == "stop": parse JSON review, return
    4. If finish_reason == "length": context exceeded, return partial
    5. Stop after max_iterations to prevent infinite loops
    6. Check cancel_event between iterations to abort superseded reviews
    """
    trace = AgentTrace(model=model)

    messages: list[ChatCompletionMessageParam] = [
        ChatCompletionSystemMessageParam(role="system", content=system_prompt),
        ChatCompletionUserMessageParam(role="user", content=user_prompt),
    ]

    tools: list[ChatCompletionToolParam] = TOOL_DEFINITIONS  # type: ignore[assignment]

    for iteration in range(1, max_iterations + 1):
        # Check for cancellation (superseded by newer push)
        if cancel_event is not None and cancel_event.is_set():
            trace.finish()
            raise AgentError("review cancelled: superseded by newer push")

        step_start = time.time()

        logger.info("agent iteration", iteration=iteration, max=max_iterations)

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                temperature=0.1,
            )
        except Exception as exc:
            trace.add_step(
                iteration,
                error=f"API call failed: {exc}",
                duration_seconds=time.time() - step_start,
            )
            trace.finish()
            raise AgentError(f"Azure OpenAI API call failed: {exc}") from exc

        choice = response.choices[0]
        message = choice.message

        # Track token usage
        if response.usage is not None:
            trace.total_prompt_tokens += response.usage.prompt_tokens
            trace.total_completion_tokens += response.usage.completion_tokens

        # Case 1: Tool calls — execute and loop
        if choice.finish_reason == "tool_calls" and message.tool_calls:
            # Append the assistant message with tool calls
            tc_params = []
            for tc in message.tool_calls:
                if not hasattr(tc, "function"):
                    continue
                tc_params.append(
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                )
            messages.append(
                ChatCompletionAssistantMessageParam(
                    role="assistant",
                    tool_calls=tc_params,  # type: ignore[typeddict-item]
                )
            )

            # Execute each tool call
            for tool_call in message.tool_calls:
                if not hasattr(tool_call, "function"):
                    continue
                tool_start = time.time()
                tool_name = tool_call.function.name

                try:
                    arguments = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError as exc:
                    tool_result = f"error: invalid JSON arguments: {exc}"
                    trace.add_step(
                        iteration,
                        tool_name=tool_name,
                        error=tool_result,
                        duration_seconds=time.time() - tool_start,
                    )
                    messages.append(
                        ChatCompletionToolMessageParam(
                            role="tool",
                            tool_call_id=tool_call.id,
                            content=tool_result,
                        )
                    )
                    continue

                try:
                    tool_result = await tool_executor.execute(tool_name, arguments)
                except Exception as exc:
                    tool_result = f"error: {exc}"
                    trace.add_step(
                        iteration,
                        tool_name=tool_name,
                        tool_arguments=arguments,
                        error=str(exc),
                        duration_seconds=time.time() - tool_start,
                    )
                else:
                    trace.add_step(
                        iteration,
                        tool_name=tool_name,
                        tool_arguments=arguments,
                        tool_result=tool_result,
                        duration_seconds=time.time() - tool_start,
                    )

                messages.append(
                    ChatCompletionToolMessageParam(
                        role="tool",
                        tool_call_id=tool_call.id,
                        content=tool_result,
                    )
                )

            continue

        # Case 2: Final response — parse and return
        if choice.finish_reason == "stop" and message.content:
            trace.add_step(
                iteration,
                duration_seconds=time.time() - step_start,
            )
            trace.finish()

            try:
                review_data = _parse_review_json(message.content)
            except (json.JSONDecodeError, ValueError) as exc:
                raise AgentError(f"failed to parse review JSON: {exc}") from exc

            return review_data, trace

        # Case 3: Context length exceeded — return partial content if available
        if choice.finish_reason == "length":
            logger.warning("context length exceeded, returning partial review")
            trace.add_step(
                iteration,
                error="context length exceeded",
                duration_seconds=time.time() - step_start,
            )
            trace.finish()

            if message.content:
                try:
                    return _parse_review_json(message.content), trace
                except (json.JSONDecodeError, ValueError):
                    pass

            return {
                "findings": [],
                "summary": "Review incomplete: context length exceeded",
            }, trace

        # Case 4: Unexpected finish reason
        trace.add_step(
            iteration,
            error=f"unexpected finish_reason: {choice.finish_reason}",
            duration_seconds=time.time() - step_start,
        )
        trace.finish()
        raise AgentError(f"unexpected finish_reason: {choice.finish_reason}")

    # Max iterations reached
    trace.finish()
    raise AgentError(f"agent exceeded max iterations ({max_iterations})")


def build_review_from_agent_result(
    review_data: dict[str, Any],
    trace: AgentTrace,
    pr: Any,
    model: str,
) -> Review:
    """Build a Review model from the agent's parsed output and trace."""
    findings = _parse_findings(review_data)
    summary = review_data.get("summary", "")

    return Review(
        pull_request=pr,
        findings=findings,
        summary=summary,
        model=model,
        duration_seconds=trace.duration_seconds,
        iterations=len(trace.steps),
        token_usage=TokenUsage(
            prompt_tokens=trace.total_prompt_tokens,
            completion_tokens=trace.total_completion_tokens,
            total_tokens=trace.total_tokens,
        ),
    )
