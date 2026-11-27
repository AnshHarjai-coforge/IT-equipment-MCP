"""Unit tests for handling one request: the printed run, and Python's escalation.

The model is a scripted fake and the MCP server a fake that returns a set
result for each tool, so no model is paid for and no server is started. The
fakes are kept to what these tests need, so this module stands on its own.
"""

import asyncio
import json

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from it_equipment.agent.handler import escalate_without_draft, handle_request
from it_equipment.agent.react_loop import LoopResult
from it_equipment.agent.request import EquipmentRequest

PRIYA_REQUEST = EquipmentRequest(
    employee_id="E001",
    text="My laptop is 4 years old and slow, can I get a replacement?",
)

FLAG_ID = "5f0c6a8e-2b1d-4e7a-9c3f-8d2e1b0a7c64"

APPROVED_REPLACEMENT = {
    "decision": "approved",
    "item": "laptop",
    "answered": "replacement",
    "message": "Your request for a replacement laptop is approved.",
    "reason": "check_request_eligibility approved a replacement laptop for E001.",
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


def draft_reply() -> Message:
    return model_reply([TextBlock(type="text", text=json.dumps(APPROVED_REPLACEMENT))], "end_turn")


def look_up_priya() -> ToolUseBlock:
    arguments = {"thought": "I need their record.", "employee_id": "E001"}
    return ToolUseBlock(type="tool_use", id="toolu_1", name="get_employee_info", input=arguments)


def flag_recorded() -> CallToolResult:
    flag = {"flag_id": FLAG_ID, "employee_id": "E001", "status": "queued"}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(flag))], structured_content=flag
    )


def flag_refused() -> CallToolResult:
    message = "Error executing tool flag_for_human_review: \"No employee with id 'E999'\""
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


class ScriptedMessages:
    """Stands in for model_client.messages: hands back the scripted replies in order."""

    def __init__(self, replies: list[Message]) -> None:
        self.replies = replies
        self.count = 0

    async def create(self, **kwargs) -> Message:
        self.count = self.count + 1
        return self.replies[self.count - 1]


class ScriptedModelClient:
    def __init__(self, replies: list[Message]) -> None:
        self.messages = ScriptedMessages(replies)


class FakeMcpClient:
    """Lists one tool, records each call, and returns the set result for each tool name."""

    def __init__(self, results: dict[str, CallToolResult]) -> None:
        self.results = results
        self.calls = []

    async def list_tools(self) -> ListToolsResult:
        schema = {"type": "object", "properties": {"employee_id": {"type": "string"}}}
        return ListToolsResult(tools=[Tool(name="get_employee_info", input_schema=schema)])

    async def call_tool(self, name: str, arguments: dict) -> CallToolResult:
        self.calls.append((name, arguments))
        return self.results[name]


def flagging_server() -> FakeMcpClient:
    return FakeMcpClient({"flag_for_human_review": flag_recorded()})


def handle(replies: list[Message], mcp_client: FakeMcpClient, max_steps=10) -> LoopResult:
    model_client = ScriptedModelClient(replies)
    return asyncio.run(
        handle_request(model_client, mcp_client, "claude-opus-5", 16000, max_steps, PRIYA_REQUEST)
    )


def test_the_user_query_is_printed_first(capsys):
    handle([draft_reply()], flagging_server())

    printed = capsys.readouterr().out
    assert printed.startswith("User query\n  From:           E001\n")


def test_a_draft_is_printed_after_the_loop(capsys):
    handle([draft_reply()], flagging_server())

    printed = capsys.readouterr().out
    assert printed.index("Step 1: ReAct loop") < printed.index("Draft after the ReAct loop")
    assert "  Decision:       approved\n" in printed


def test_a_draft_is_not_flagged_by_python():
    mcp_client = flagging_server()

    handle([draft_reply()], mcp_client)

    assert mcp_client.calls == []


def test_a_refusal_is_sent_to_a_person_by_python():
    mcp_client = flagging_server()

    handle([model_reply([], "refusal")], mcp_client)

    assert mcp_client.calls == [
        (
            "flag_for_human_review",
            {
                "employee_id": "E001",
                "request": "My laptop is 4 years old and slow, can I get a replacement?",
                "reason": "The agent could not reach a decision: the model refused.",
            },
        )
    ]


def test_the_step_limit_is_sent_to_a_person_by_python():
    mcp_client = FakeMcpClient(
        {
            "get_employee_info": flag_recorded(),
            "flag_for_human_review": flag_recorded(),
        }
    )

    always_asks = [
        model_reply([look_up_priya()], "tool_use"),
        model_reply([look_up_priya()], "tool_use"),
    ]

    handle(always_asks, mcp_client, max_steps=2)

    name, arguments = mcp_client.calls[-1]
    assert name == "flag_for_human_review"
    assert arguments["reason"] == (
        "The agent could not reach a decision: it reached the limit of 2 calls to the model."
    )


def test_a_run_with_no_draft_ends_with_the_stopped_line_and_the_flag(capsys):
    handle([model_reply([], "refusal")], flagging_server())

    printed = capsys.readouterr().out
    assert printed.endswith(
        "\nStep 1: ReAct loop\n"
        "\n"
        "  The ReAct loop stopped: the model refused, so there is no draft.\n"
        f"  Python sent the request to a person instead: flag id {FLAG_ID}.\n"
    )


def test_a_flag_the_tool_refuses_prints_the_tools_error(capsys):
    unknown = EquipmentRequest(employee_id="E999", text="I need a new monitor.")
    mcp_client = FakeMcpClient({"flag_for_human_review": flag_refused()})

    asyncio.run(escalate_without_draft(mcp_client, unknown, "the model refused"))

    printed = capsys.readouterr().out
    assert printed.startswith("  Python could not send the request to a person:")
    assert "'E999'" in printed


def test_handle_request_returns_how_the_loop_ended():
    result = handle([model_reply([], "refusal")], flagging_server())

    assert result.draft is None
    assert result.stopped_because == "the model refused"
