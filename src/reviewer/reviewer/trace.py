"""Agent trace recording for observability.

Records each step of the agent's tool-use loop for debugging and auditing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceStep:
    """A single step in the agent's execution."""

    step_number: int
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    tool_result: str = ""
    error: str = ""
    duration_seconds: float = 0.0


@dataclass
class AgentTrace:
    """Complete trace of an agent's review execution."""

    model: str = ""
    steps: list[TraceStep] = field(default_factory=list)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    @property
    def duration_seconds(self) -> float:
        if self.end_time == 0.0:
            return time.time() - self.start_time
        return self.end_time - self.start_time

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    def add_step(
        self,
        step_number: int,
        *,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        tool_result: str = "",
        error: str = "",
        duration_seconds: float = 0.0,
    ) -> TraceStep:
        step = TraceStep(
            step_number=step_number,
            tool_name=tool_name,
            tool_arguments=tool_arguments or {},
            tool_result=tool_result,
            error=error,
            duration_seconds=duration_seconds,
        )
        self.steps.append(step)
        return step

    def finish(self) -> None:
        self.end_time = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "duration_seconds": self.duration_seconds,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "steps": [
                {
                    "step": s.step_number,
                    "tool": s.tool_name,
                    "arguments": s.tool_arguments,
                    "result_length": len(s.tool_result),
                    "error": s.error,
                    "duration_seconds": s.duration_seconds,
                }
                for s in self.steps
            ],
        }
