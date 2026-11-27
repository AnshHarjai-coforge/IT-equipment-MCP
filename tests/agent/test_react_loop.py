"""Unit tests for the ReAct loop.

The model is a scripted fake: it hands back a list of real anthropic Message
objects, one per call, in order, and records what each call was sent. The MCP
server is a fake that returns a set result for each tool name and records each
call. No model is paid for and no server is started, so a failure points at
the loop itself.

run_react_loop is asynchronous, so each test runs it with asyncio.run, from
the standard library. Printed output is read back with pytest's capsys.
"""

import asyncio
import json

from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from it_equipment.agent.draft import DRAFT_FORMAT
from it_equipment.agent.prompts import SYSTEM_PROMPT
from it_equipment.agent.react_loop import LoopResult, run_react_loop, why_the_model_stopped
from it_equipment.agent.request import EquipmentRequest

PRIYA_REQUEST = EquipmentRequest(
    employee_id="E001",
    text="My laptop is 4 years old and slow, can I get a replacement?",
)

# Priya's record, as get_employee_info returns it.
PRIYA = {
    "employee_id": "E001",
    "name": "Priya Raman",
    "role": "standard",
    "tenure_years": 7,
    "equipment": [{"name": "laptop", "age_years": 4}, {"name": "monitor", "age_years": 4}],
}

# Priya's laptop verdicts, as check_request_eligibility returns them.
LAPTOP_VERDICTS = {
    "employee_id": "E001",
    "role": "standard",
    "item": "laptop",
    "held": 1,
    "max_quantity": 1,
    "refresh_years": 4,
    "additional": {
        "verdict": "denied",
        "reason": (
            "Employees in the standard role may hold 1 laptop and E001 holds 1. Another "
            "laptop is not issued while 1 laptop is held, so there is no date on which "
            "this changes."
        ),
        "next_eligible_on": None,
    },
    "replacement": {
        "verdict": "approved",
        "reason": (
            "E001's laptop is 4 years old; laptops in the standard role are replaced after 4 years."
        ),
        "next_eligible_on": None,
    },
}

APPROVED_REPLACEMENT = {
    "decision": "approved",
    "item": "laptop",
    "answered": "replacement",
    "message": "Your request for a replacement laptop is approved.",
    "reason": "check_request_eligibility approved a replacement laptop for E001.",
    "flag_id": None,
}

LOOK_UP_THOUGHT = "I need their role and how old their laptop is."
CHECK_THOUGHT = "They want a new laptop in place of the old one, so replacement applies."


def tool(name: str, arguments: list[str]) -> Tool:
    properties = {}
    for argument in arguments:
        properties[argument] = {"type": "string"}
    schema = {"type": "object", "properties": properties, "required": arguments}
    return Tool(name=name, description=f"The {name} tool.", input_schema=schema)


def look_up_priya() -> ToolUseBlock:
    arguments = {"thought": LOOK_UP_THOUGHT, "employee_id": "E001"}
    return ToolUseBlock(type="tool_use", id="toolu_1", name="get_employee_info", input=arguments)


def check_priyas_laptop() -> ToolUseBlock:
    arguments = {"thought": CHECK_THOUGHT, "employee_id": "E001", "item": "laptop"}
    return ToolUseBlock(
        type="tool_use", id="toolu_2", name="check_request_eligibility", input=arguments
    )


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


def draft_reply() -> Message:
    """The model's last reply: its draft, as JSON text."""
    text = TextBlock(type="text", text=json.dumps(APPROVED_REPLACEMENT))
    return model_reply([text], "end_turn")


def found(structured: dict) -> CallToolResult:
    text = TextContent(type="text", text=json.dumps(structured, indent=2))
    return CallToolResult(content=[text], structured_content=structured)


def no_such_employee() -> CallToolResult:
    message = "Error executing tool get_employee_info: \"No employee with id 'E999'\""
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)


class ScriptedMessages:
    """Stands in for model_client.messages: hands back the scripted replies in order."""

    def __init__(self, replies: list[Message]) -> None:
        self.replies = replies
        self.requests = []

    async def create(self, **kwargs) -> Message:
        # The loop keeps adding to one list of messages, so a copy of the list
        # is kept: what this call was sent, not what the list later became.
        sent = dict(kwargs)
        sent["messages"] = list(kwargs["messages"])
        self.requests.append(sent)

        # Running out of replies fails the test with an IndexError, which
        # means the loop called the model more often than the script expects.
        return self.replies[len(self.requests) - 1]


class ScriptedModelClient:
    """Stands in for AsyncAnthropicFoundry, of which only messages.create is used."""

    def __init__(self, replies: list[Message]) -> None:
        self.messages = ScriptedMessages(replies)


class FakeMcpClient:
    """Stands in for the MCP client: lists two tools, records each call, returns a set result."""

    def __init__(self, results: dict[str, CallToolResult]) -> None:
        self.results = results
        self.calls = []

    async def list_tools(self) -> ListToolsResult:
        return ListToolsResult(
            tools=[
                tool("get_employee_info", ["employee_id"]),
                tool("check_request_eligibility", ["employee_id", "item"]),
            ]
        )

    async def call_tool(self, name: str, arguments: dict) -> CallToolResult:
        self.calls.append((name, arguments))
        return self.results[name]


def priyas_server() -> FakeMcpClient:
    return FakeMcpClient(
        {"get_employee_info": found(PRIYA), "check_request_eligibility": found(LAPTOP_VERDICTS)}
    )


def run(model_client: ScriptedModelClient, mcp_client: FakeMcpClient, max_steps=10) -> LoopResult:
    """Run the loop for Priya's request, as the agent does."""
    return asyncio.run(
        run_react_loop(model_client, mcp_client, "claude-opus-5", 16000, max_steps, PRIYA_REQUEST)
    )


def three_replies() -> list[Message]:
    """Look Priya up, then check the laptop, then write the draft."""
    return [
        model_reply([look_up_priya()], "tool_use"),
        model_reply([check_priyas_laptop()], "tool_use"),
        draft_reply(),
    ]


def test_the_model_is_sent_only_the_six_agreed_arguments():
    """No thinking: the Thought on each tool call is the reasoning shown."""
    model_client = ScriptedModelClient([draft_reply()])

    run(model_client, priyas_server())

    sent = model_client.messages.requests[0]
    assert sorted(sent.keys()) == [
        "max_tokens",
        "messages",
        "model",
        "output_config",
        "system",
        "tools",
    ]


def test_the_settings_passed_in_are_the_ones_sent():
    model_client = ScriptedModelClient([draft_reply()])

    asyncio.run(
        run_react_loop(model_client, priyas_server(), "my-deployment", 4000, 10, PRIYA_REQUEST)
    )

    sent = model_client.messages.requests[0]
    assert sent["model"] == "my-deployment"
    assert sent["max_tokens"] == 4000


def test_the_system_prompt_and_the_draft_format_are_sent_on_every_call():
    model_client = ScriptedModelClient(three_replies())

    run(model_client, priyas_server())

    for sent in model_client.messages.requests:
        assert sent["system"] == SYSTEM_PROMPT
        assert sent["output_config"] == {"format": DRAFT_FORMAT}


def test_the_first_message_is_the_request_as_prompt_text():
    model_client = ScriptedModelClient([draft_reply()])

    run(model_client, priyas_server())

    first = model_client.messages.requests[0]["messages"]
    assert first == [{"role": "user", "content": PRIYA_REQUEST.prompt_text()}]


def test_the_model_is_offered_the_servers_tools_with_a_thought():
    model_client = ScriptedModelClient([draft_reply()])

    run(model_client, priyas_server())

    offered = model_client.messages.requests[0]["tools"]
    assert list(offered[0]["input_schema"]["properties"].keys()) == ["thought", "employee_id"]


def test_a_tool_call_is_run_on_the_server_without_the_thought():
    mcp_client = priyas_server()

    run(ScriptedModelClient(three_replies()), mcp_client)

    assert mcp_client.calls[0] == ("get_employee_info", {"employee_id": "E001"})


def test_the_models_reply_goes_back_unchanged_thinking_included():
    thinking = ThinkingBlock(type="thinking", thinking="", signature="sig-abc")
    first_reply = model_reply([thinking, look_up_priya()], "tool_use")
    model_client = ScriptedModelClient([first_reply, draft_reply()])

    run(model_client, priyas_server())

    second = model_client.messages.requests[1]["messages"]
    assert second[1] == {"role": "assistant", "content": first_reply.content}


def test_the_tool_result_goes_back_in_the_next_message():
    model_client = ScriptedModelClient([model_reply([look_up_priya()], "tool_use"), draft_reply()])

    run(model_client, priyas_server())

    second = model_client.messages.requests[1]["messages"]
    assert second[2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": json.dumps(PRIYA, indent=2),
                "is_error": False,
            }
        ],
    }


def test_an_error_result_goes_back_marked_as_an_error():
    model_client = ScriptedModelClient([model_reply([look_up_priya()], "tool_use"), draft_reply()])
    mcp_client = FakeMcpClient({"get_employee_info": no_such_employee()})

    run(model_client, mcp_client)

    result = model_client.messages.requests[1]["messages"][2]["content"][0]
    assert result["is_error"] is True
    assert "No employee with id 'E999'" in result["content"]


def test_several_tool_calls_in_one_reply_all_run_in_the_order_asked():
    both = model_reply([look_up_priya(), check_priyas_laptop()], "tool_use")
    mcp_client = priyas_server()

    run(ScriptedModelClient([both, draft_reply()]), mcp_client)

    assert mcp_client.calls == [
        ("get_employee_info", {"employee_id": "E001"}),
        ("check_request_eligibility", {"employee_id": "E001", "item": "laptop"}),
    ]


def test_several_results_go_back_in_one_message_in_the_order_asked():
    both = model_reply([look_up_priya(), check_priyas_laptop()], "tool_use")
    model_client = ScriptedModelClient([both, draft_reply()])

    run(model_client, priyas_server())

    second = model_client.messages.requests[1]["messages"]
    ids = []
    for block in second[2]["content"]:
        ids.append(block["tool_use_id"])
    assert len(second) == 3
    assert ids == ["toolu_1", "toolu_2"]


def test_steps_are_numbered_across_the_whole_loop():
    """Two calls from the first reply and one from the next are 1, 2 and 3."""
    first = model_reply([look_up_priya(), check_priyas_laptop()], "tool_use")
    second = model_reply([check_priyas_laptop()], "tool_use")
    model_client = ScriptedModelClient([first, second, draft_reply()])

    result = run(model_client, priyas_server())

    numbers = []
    for step in result.trace:
        numbers.append(step.number)
    assert numbers == [1, 2, 3]


def test_each_step_keeps_its_thought_the_call_and_the_result():
    result = run(ScriptedModelClient(three_replies()), priyas_server())

    step = result.trace[1]
    assert step.thought == CHECK_THOUGHT
    assert step.tool_name == "check_request_eligibility"
    assert step.arguments == {"employee_id": "E001", "item": "laptop"}
    assert step.observation == json.dumps(LAPTOP_VERDICTS, indent=2)
    assert step.is_error is False


def test_the_loop_ends_with_the_draft_on_end_turn():
    model_client = ScriptedModelClient(three_replies())

    result = run(model_client, priyas_server())

    assert result.draft.decision == "approved"
    assert result.draft.answered == "replacement"
    assert result.stopped_because == ""
    assert len(model_client.messages.requests) == 3


def test_a_final_reply_that_is_not_a_draft_ends_without_one():
    prose = model_reply([TextBlock(type="text", text="Approved!")], "end_turn")

    result = run(ScriptedModelClient([prose]), priyas_server())

    assert result.draft is None
    assert result.stopped_because == "the model's final reply could not be read as a draft"


def test_a_refusal_ends_the_loop_without_a_draft():
    result = run(ScriptedModelClient([model_reply([], "refusal")]), priyas_server())

    assert result.draft is None
    assert result.stopped_because == "the model refused"


def test_a_tool_call_cut_off_at_max_tokens_is_not_run():
    """Its arguments may be half-written, so it is not something to run."""
    cut_off = model_reply([look_up_priya()], "max_tokens")
    mcp_client = priyas_server()

    result = run(ScriptedModelClient([cut_off]), mcp_client)

    assert mcp_client.calls == []
    assert result.stopped_because == "the model's reply was cut off at the limit of 16000 tokens"


def test_the_step_limit_ends_the_loop_without_a_draft():
    always_asks = []
    for _ in range(3):
        always_asks.append(model_reply([look_up_priya()], "tool_use"))
    model_client = ScriptedModelClient(always_asks)

    result = run(model_client, priyas_server(), max_steps=3)

    assert len(model_client.messages.requests) == 3
    assert result.draft is None
    assert result.stopped_because == "it reached the limit of 3 calls to the model"


def test_tool_use_with_no_tool_call_ends_the_loop_without_a_draft():
    empty = model_reply([TextBlock(type="text", text="Let me check.")], "tool_use")

    result = run(ScriptedModelClient([empty]), priyas_server())

    assert result.draft is None
    assert result.stopped_because == "the model said it would call a tool but asked for none"


def test_each_step_is_printed_under_the_loop_heading(capsys):
    run(ScriptedModelClient(three_replies()), priyas_server())

    printed = capsys.readouterr().out
    assert printed.startswith("\nStep 1: ReAct loop\n\n  Thought 1:      I need their role")
    action = '  Action 2:       check_request_eligibility(employee_id="E001", item="laptop")'
    assert action in printed
    assert '  Observation 2:  {\n                    "employee_id": "E001",' in printed


def test_a_context_window_stop_is_explained_in_words():
    why = why_the_model_stopped("model_context_window_exceeded", 16000)

    assert why == "the conversation grew too long for the model to read"


def test_an_unexpected_stop_reason_is_named():
    why = why_the_model_stopped("pause_turn", 16000)

    assert why == "the model stopped for a reason the agent does not handle (pause_turn)"
