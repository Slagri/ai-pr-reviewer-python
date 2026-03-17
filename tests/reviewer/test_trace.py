"""Tests for agent trace recording."""

from __future__ import annotations

import time

from reviewer.reviewer.trace import AgentTrace, TraceStep


class TestTraceStep:
    """Test individual trace steps."""

    def test_default_values(self) -> None:
        step = TraceStep(step_number=1)
        assert step.tool_name is None
        assert step.tool_arguments == {}
        assert step.tool_result == ""
        assert step.error == ""
        assert step.duration_seconds == 0.0


class TestAgentTrace:
    """Test complete agent traces."""

    def test_empty_trace(self) -> None:
        trace = AgentTrace(model="gpt-5.4")
        assert trace.model == "gpt-5.4"
        assert trace.steps == []
        assert trace.total_tokens == 0

    def test_add_step(self) -> None:
        trace = AgentTrace()
        step = trace.add_step(
            1,
            tool_name="get_file_content",
            tool_arguments={"path": "src/main.py"},
            tool_result="print('hello')",
            duration_seconds=0.5,
        )
        assert len(trace.steps) == 1
        assert step.tool_name == "get_file_content"
        assert step.duration_seconds == 0.5

    def test_duration_before_finish(self) -> None:
        trace = AgentTrace()
        # Duration should be measured from start_time to now
        assert trace.duration_seconds >= 0

    def test_duration_after_finish(self) -> None:
        trace = AgentTrace()
        time.sleep(0.01)
        trace.finish()
        duration = trace.duration_seconds
        assert duration >= 0.01
        # Duration should be stable after finish
        assert trace.duration_seconds == duration

    def test_token_tracking(self) -> None:
        trace = AgentTrace()
        trace.total_prompt_tokens = 1000
        trace.total_completion_tokens = 500
        assert trace.total_tokens == 1500

    def test_to_dict(self) -> None:
        trace = AgentTrace(model="gpt-5.4")
        trace.total_prompt_tokens = 100
        trace.total_completion_tokens = 50
        trace.add_step(1, tool_name="get_file_content", tool_result="content")
        trace.finish()

        d = trace.to_dict()
        assert d["model"] == "gpt-5.4"
        assert d["total_tokens"] == 150
        assert len(d["steps"]) == 1
        assert d["steps"][0]["tool"] == "get_file_content"
        assert d["steps"][0]["result_length"] == 7  # len("content")
