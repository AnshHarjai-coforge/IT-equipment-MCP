"""Unit tests for the agent's first tool call and what it prints.

The model and the MCP server are both replaced by plain fake classes, so no
model is paid for, no server is started, and every run gives the same result.
The fakes hand back real anthropic and mcp objects built from literals, so the
agent meets exactly the shapes it gets for real.

run_first_tool_call is asynchronous, so each test runs it with asyncio.run,
from the standard library. Tests that check what is printed read it back with
pytest's capsys.
"""

import asyncio
import json

import pytest
from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from it_equipment.agent.first_call import (
    HARDCODED_REQUEST,
    NoToolCallError,
    run_first_tool_call,
)
from it_equipment.agent.prompts import SYSTEM_PROMPT
from it_equipment.agent.trace import TraceStep

# Priya's record as get_employee_info returns it.
PRIYA = {
    "employee_id": "E001",
    "name": "Priya Raman",
    "role": "standard",
    "tenure_years": 7,
    "equipment": [{"name": "laptop", "age_years": 4}, {"name": "monitor", "age_years": 4}],
}

LOOK_UP_THOUGHT = "I need her role and how old her laptop is."


def employee_info_tool() -> Tool:
    return Tool(
        name="get_employee_info",
        description="Get an employee's role.",
        input_schema={
            "type": "object",
            "properties": {"employee_id": {"title": "Employee Id", "type": "string"}},
            "required": ["employee_id"],
        },
    )


def tool_call(name: str, arguments: dict, call_id: str) -> ToolUseBlock:
    return ToolUseBlock(type="tool_use", id=call_id, name=name, input=arguments)


def look_up_priya() -> ToolUseBlock:
    """The call the model is expected to make first, thought included."""
    arguments = {"thought": LOOK_UP_THOUGHT, "employee_id": "E001"}
    return tool_call("get_employee_info", arguments, "toolu_1")


def model_reply(content: list, stop_reason: str) -> Message:
    """A real Message, shaped as the SDK returns one."""
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


def priya_found() -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(PRIYA, indent=2))],
        structured_content=PRIYA,
    )


def no_such_employee() -> CallToolResult:
    message = "Error executing tool get_employee_info: \"No employee with id 'E999'\""
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


class FakeMessages:
    """Stands in for model_client.messages: records each request, returns a set reply."""

    def __init__(self, reply: Message) -> None:
        self.reply = reply
        self.requests = []

    async def create(self, **kwargs) -> Message:
        self.requests.append(kwargs)
        return self.reply


class FakeModelClient:
    """Stands in for AsyncAnthropicFoundry, of which only messages.create is used."""

    def __init__(self, reply: Message) -> None:
        self.messages = FakeMessages(reply)


class FakeMcpClient:
    """Stands in for the MCP client: lists one tool, records each call, returns a set result."""

    def __init__(self, result: CallToolResult) -> None:
        self.result = result
        self.calls = []

    async def list_tools(self) -> ListToolsResult:
        return ListToolsResult(tools=[employee_info_tool()])

    async def call_tool(self, name: str, arguments: dict) -> CallToolResult:
        self.calls.append((name, arguments))
        return self.result


def run(model_client: FakeModelClient, mcp_client: FakeMcpClient) -> TraceStep:
    """Run the first tool call for the hardcoded request, as main() does."""
    return asyncio.run(
        run_first_tool_call(model_client, mcp_client, "claude-opus-5", 16000, HARDCODED_REQUEST)
    )


def test_the_model_is_sent_only_the_agreed_arguments():
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    run(model_client, FakeMcpClient(priya_found()))

    sent = model_client.messages.requests[0]
    assert sorted(sent.keys()) == ["max_tokens", "messages", "model", "system", "thinking", "tools"]


def test_the_model_passed_in_is_the_one_called():
    """The Foundry deployment name, from the settings."""
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))
    mcp_client = FakeMcpClient(priya_found())

    asyncio.run(
        run_first_tool_call(
            model_client, mcp_client, "my-opus-deployment", 16000, HARDCODED_REQUEST
        )
    )

    assert model_client.messages.requests[0]["model"] == "my-opus-deployment"


def test_the_reply_limit_passed_in_is_the_one_sent():
    """max_tokens from the settings."""
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))
    mcp_client = FakeMcpClient(priya_found())

    asyncio.run(
        run_first_tool_call(model_client, mcp_client, "claude-opus-5", 4000, HARDCODED_REQUEST)
    )

    assert model_client.messages.requests[0]["max_tokens"] == 4000


def test_the_request_is_sent_as_one_user_message():
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    run(model_client, FakeMcpClient(priya_found()))

    sent = model_client.messages.requests[0]
    assert sent["messages"] == [{"role": "user", "content": HARDCODED_REQUEST}]


def test_the_system_prompt_is_sent():
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    run(model_client, FakeMcpClient(priya_found()))

    assert model_client.messages.requests[0]["system"] == SYSTEM_PROMPT


def test_a_summary_of_the_thinking_is_asked_for():
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    run(model_client, FakeMcpClient(priya_found()))

    sent = model_client.messages.requests[0]
    assert sent["thinking"] == {"type": "adaptive", "display": "summarized"}


def test_the_model_is_offered_the_servers_tools_with_a_thought():
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    run(model_client, FakeMcpClient(priya_found()))

    offered = model_client.messages.requests[0]["tools"]
    assert offered[0]["name"] == "get_employee_info"
    assert list(offered[0]["input_schema"]["properties"].keys()) == ["thought", "employee_id"]


def test_the_server_is_called_without_the_thought():
    mcp_client = FakeMcpClient(priya_found())

    run(FakeModelClient(model_reply([look_up_priya()], "tool_use")), mcp_client)

    assert mcp_client.calls == [("get_employee_info", {"employee_id": "E001"})]


def test_the_step_keeps_the_thought():
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    step = run(model_client, FakeMcpClient(priya_found()))

    assert step.thought == LOOK_UP_THOUGHT


def test_the_step_holds_what_the_server_was_called_with():
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    step = run(model_client, FakeMcpClient(priya_found()))

    assert step.tool_name == "get_employee_info"
    assert step.arguments == {"employee_id": "E001"}


def test_the_step_holds_the_result_as_indented_json():
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    step = run(model_client, FakeMcpClient(priya_found()))

    assert step.observation == json.dumps(PRIYA, indent=2)
    assert step.is_error is False


def test_an_error_result_is_marked_as_an_error_in_the_step():
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    step = run(model_client, FakeMcpClient(no_such_employee()))

    assert step.is_error is True
    assert "No employee with id 'E999'" in step.observation


def test_a_reply_that_ends_in_text_raises_no_tool_call_error():
    answer = TextBlock(type="text", text="Your laptop can be replaced.")
    model_client = FakeModelClient(model_reply([answer], "end_turn"))

    with pytest.raises(NoToolCallError):
        run(model_client, FakeMcpClient(priya_found()))


def test_no_tool_call_error_carries_the_stop_reason_and_the_text():
    answer = TextBlock(type="text", text="Your laptop can be replaced.")
    model_client = FakeModelClient(model_reply([answer], "end_turn"))

    with pytest.raises(NoToolCallError) as caught:
        run(model_client, FakeMcpClient(priya_found()))

    assert caught.value.stop_reason == "end_turn"
    assert caught.value.text == "Your laptop can be replaced."


def test_a_refusal_raises_no_tool_call_error():
    model_client = FakeModelClient(model_reply([], "refusal"))

    with pytest.raises(NoToolCallError, match="refusal"):
        run(model_client, FakeMcpClient(priya_found()))


def test_a_tool_call_cut_off_at_max_tokens_is_not_run():
    """Its arguments may be half-written, so it is not something to run."""
    model_client = FakeModelClient(model_reply([look_up_priya()], "max_tokens"))
    mcp_client = FakeMcpClient(priya_found())

    with pytest.raises(NoToolCallError, match="max_tokens"):
        run(model_client, mcp_client)

    assert mcp_client.calls == []


def test_only_the_first_of_several_tool_calls_is_run():
    check_laptop = tool_call(
        "check_request_eligibility",
        {"thought": "Then the laptop rules.", "employee_id": "E001", "item": "laptop"},
        "toolu_2",
    )
    model_client = FakeModelClient(model_reply([look_up_priya(), check_laptop], "tool_use"))
    mcp_client = FakeMcpClient(priya_found())

    run(model_client, mcp_client)

    assert mcp_client.calls == [("get_employee_info", {"employee_id": "E001"})]


def test_a_tool_call_that_is_not_run_is_still_printed(capsys):
    check_laptop = tool_call(
        "check_request_eligibility",
        {"thought": "Then the laptop rules.", "employee_id": "E001", "item": "laptop"},
        "toolu_2",
    )
    model_client = FakeModelClient(model_reply([look_up_priya(), check_laptop], "tool_use"))

    run(model_client, FakeMcpClient(priya_found()))

    printed = capsys.readouterr().out
    assert "Tool call 2 of 2  (not run: this branch runs only the first)" in printed
    assert "  Thought 2:      Then the laptop rules." in printed
    action = '  Action 2:       check_request_eligibility(employee_id="E001", item="laptop")'
    assert action in printed


def test_the_request_is_printed_first(capsys):
    model_client = FakeModelClient(model_reply([look_up_priya()], "tool_use"))

    run(model_client, FakeMcpClient(priya_found()))

    printed = capsys.readouterr().out
    assert printed.startswith("Request\n  " + HARDCODED_REQUEST + "\n")


def test_the_thinking_summary_and_the_text_are_printed(capsys):
    thinking = ThinkingBlock(type="thinking", thinking="She wants a new laptop.", signature="sig")
    text = TextBlock(type="text", text="I'll look up her record first.")
    model_client = FakeModelClient(model_reply([thinking, text, look_up_priya()], "tool_use"))

    run(model_client, FakeMcpClient(priya_found()))

    printed = capsys.readouterr().out
    assert "Model reply  (stop reason: tool_use)" in printed
    assert "  Thinking:       She wants a new laptop." in printed
    assert "  Text:           I'll look up her record first." in printed


def test_thinking_with_no_summary_prints_no_thinking_line(capsys):
    thinking = ThinkingBlock(type="thinking", thinking="", signature="sig")
    model_client = FakeModelClient(model_reply([thinking, look_up_priya()], "tool_use"))

    run(model_client, FakeMcpClient(priya_found()))

    assert "Thinking:" not in capsys.readouterr().out
