"""Unit tests for the eval runner: its command line, one run, every run, and the exit rule.

The model is a scripted fake that hands back real anthropic Message objects,
and confirms the draft whenever reflection calls it; the MCP server is a fake
that returns a set result per tool. So nothing is paid for and no server is
started. main() itself opens the real model client
and builds the real server, so it is checked by hand, offline, against a stub
model. The async functions run with asyncio.run, from the standard library.
"""

import asyncio
import json

import httpx2
import pytest
from anthropic import APIConnectionError
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from it_equipment.agent.request import EquipmentRequest
from it_equipment.evals.cases import EvalCase, ExpectedOutcome, ToolCall
from it_equipment.evals.cli import (
    every_run_passed,
    run_case,
    run_every_case,
    runs_from_command_line,
)
from it_equipment.evals.grading import RunGrade
from it_equipment.evals.scorecard import CaseRun

# Demo request 5, as the case file has it.
UNKNOWN_ID_CASE = EvalCase(
    case_id="5-not-processed-unknown-id",
    summary="Not processed: unknown employee.",
    request=EquipmentRequest(employee_id="E999", text="I need a new monitor."),
    expected=ExpectedOutcome(
        decision="not_processed", item="monitor", answered=None, flagged=False
    ),
    verdicts=None,
    required_calls=[ToolCall(tool="get_employee_info", arguments={"employee_id": "E999"})],
    forbidden_calls=[ToolCall(tool="flag_for_human_review", arguments={})],
)

NOT_PROCESSED = {
    "decision": "not_processed",
    "item": "monitor",
    "answered": None,
    "message": "No employee has the id E999. Please check your id.",
    "reason": "get_employee_info found no employee with id E999.",
    "flag_id": None,
}


def model_reply(content: list, stop_reason: str) -> Message:
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-opus-5",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=100, output_tokens=50),
    )


def look_up_e999() -> Message:
    arguments = {"thought": "Check the sender exists.", "employee_id": "E999"}
    call = ToolUseBlock(type="tool_use", id="toolu_1", name="get_employee_info", input=arguments)
    return model_reply([call], "tool_use")


def draft(fields: dict) -> Message:
    return model_reply([TextBlock(type="text", text=json.dumps(fields))], "end_turn")


# Reflection's answer in every run here. A confirmation keeps the loop's draft
# whatever final says, so one review serves every draft these tests script.
CONFIRMING_REVIEW = draft(
    {
        "assessment": "confirmed",
        "problems": [],
        "checked": "The decision against Observation 1, which refused E999.",
        "final": NOT_PROCESSED,
    }
)


class ScriptedMessages:
    """Hands back the loop's scripted replies in order, starting again for each new run.

    Reflection's call is answered with CONFIRMING_REVIEW instead.
    """

    def __init__(self, replies: list[Message]) -> None:
        self.replies = replies
        self.count = 0

    async def create(self, **kwargs) -> Message:
        # Reflection's call is the only one sent with no tools.
        if "tools" not in kwargs:
            return CONFIRMING_REVIEW

        # The first message of a loop is the request alone, so that is where
        # the script starts again.
        if len(kwargs["messages"]) == 1:
            self.count = 0
        self.count = self.count + 1
        return self.replies[self.count - 1]


class UnreachableMessages:
    async def create(self, **kwargs) -> Message:
        request = httpx2.Request("POST", "https://example.invalid/anthropic/v1/messages")
        raise APIConnectionError(request=request)


class FakeModelClient:
    def __init__(self, messages) -> None:
        self.messages = messages


class FakeMcpClient:
    """Lists one tool, and refuses every lookup as the server does for E999."""

    async def list_tools(self) -> ListToolsResult:
        schema = {"type": "object", "properties": {"employee_id": {"type": "string"}}}
        return ListToolsResult(tools=[Tool(name="get_employee_info", input_schema=schema)])

    async def call_tool(self, name: str, arguments: dict) -> CallToolResult:
        message = f"Error executing tool {name}: \"No employee with id 'E999'\""
        return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


def run_once(messages) -> CaseRun:
    model_client = FakeModelClient(messages)
    return asyncio.run(
        run_case(model_client, FakeMcpClient(), "claude-opus-5", 16000, 10, UNKNOWN_ID_CASE, 1)
    )


def test_each_case_runs_once_by_default():
    assert runs_from_command_line([]) == 1


def test_repeat_sets_the_number_of_runs():
    assert runs_from_command_line(["--repeat", "3"]) == 3


def test_a_repeat_below_one_exits_with_status_2(capsys):
    with pytest.raises(SystemExit) as stopped:
        runs_from_command_line(["--repeat", "0"])

    assert stopped.value.code == 2
    assert "error: --repeat must be at least 1" in capsys.readouterr().err


def test_a_repeat_that_is_not_a_number_exits_with_status_2():
    with pytest.raises(SystemExit) as stopped:
        runs_from_command_line(["--repeat", "three"])

    assert stopped.value.code == 2


def test_a_run_that_matches_its_case_passes():
    case_run = run_once(ScriptedMessages([look_up_e999(), draft(NOT_PROCESSED)]))

    assert case_run == CaseRun(
        case_id="5-not-processed-unknown-id",
        run_number=1,
        grade=RunGrade(problems=[]),
        model_calls=3,
    )


def test_a_run_that_differs_from_its_case_fails():
    # A different item, which the Python check lets through, so the final
    # answer keeps it. A wrong decision would end as Python's escalation.
    about_a_laptop = dict(NOT_PROCESSED)
    about_a_laptop["item"] = "laptop"

    case_run = run_once(ScriptedMessages([look_up_e999(), draft(about_a_laptop)]))

    assert case_run.grade.problems == ["Item: expected monitor; the final answer says laptop."]


def test_the_agents_trace_is_printed_during_the_run(capsys):
    run_once(ScriptedMessages([look_up_e999(), draft(NOT_PROCESSED)]))

    printed = capsys.readouterr().out
    assert printed.startswith("User query\n  From:           E999\n")
    assert "  Decision:       not_processed\n" in printed


def test_a_failed_model_call_fails_the_run_with_the_error():
    case_run = run_once(UnreachableMessages())

    assert case_run.grade.problems == [
        "The model call failed: APIConnectionError: Connection error."
    ]
    assert case_run.model_calls == 1


def test_every_case_runs_its_repeats_together():
    second_case = EvalCase(
        case_id="5b-the-same-again",
        summary=UNKNOWN_ID_CASE.summary,
        request=UNKNOWN_ID_CASE.request,
        expected=UNKNOWN_ID_CASE.expected,
        verdicts=None,
        required_calls=UNKNOWN_ID_CASE.required_calls,
        forbidden_calls=UNKNOWN_ID_CASE.forbidden_calls,
    )
    model_client = FakeModelClient(ScriptedMessages([look_up_e999(), draft(NOT_PROCESSED)]))

    case_runs = asyncio.run(
        run_every_case(
            model_client,
            FakeMcpClient(),
            "claude-opus-5",
            16000,
            10,
            [UNKNOWN_ID_CASE, second_case],
            2,
        )
    )

    order = []
    for case_run in case_runs:
        order.append((case_run.case_id, case_run.run_number))
    assert order == [
        ("5-not-processed-unknown-id", 1),
        ("5-not-processed-unknown-id", 2),
        ("5b-the-same-again", 1),
        ("5b-the-same-again", 2),
    ]


def test_each_run_is_printed_as_heading_trace_then_result(capsys):
    model_client = FakeModelClient(ScriptedMessages([look_up_e999(), draft(NOT_PROCESSED)]))

    asyncio.run(
        run_every_case(
            model_client, FakeMcpClient(), "claude-opus-5", 16000, 10, [UNKNOWN_ID_CASE], 1
        )
    )

    printed = capsys.readouterr().out
    assert printed.startswith(
        "Case 5-not-processed-unknown-id, run 1 of 1\n"
        "  Expected:       Not processed: unknown employee.\n"
        "\n"
        "User query\n"
    )
    assert printed.endswith("  Model calls:    3\n\n")


def test_one_failed_run_means_not_every_run_passed():
    passed = CaseRun("1-approved-replacement", 1, RunGrade(problems=[]), 3)
    failed = CaseRun("1-approved-replacement", 2, RunGrade(problems=["A problem."]), 3)

    assert every_run_passed([passed, failed]) is False


def test_runs_with_no_problems_all_pass():
    passed = CaseRun("8-escalated-injection", 1, RunGrade(problems=[]), 4)

    assert every_run_passed([passed]) is True
