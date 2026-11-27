"""Unit tests for handling one request: the printed run, and the answer it ends with.

The model is a scripted fake that hands back its replies in order: the loop's,
then reflection's, which is always the last call. The MCP server is a fake that
returns a set result for each tool and records each call. So no model is paid
for and no server is started. The fakes are kept to what these tests need, so
this module stands on its own.
"""

import asyncio
import json

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from it_equipment.agent.draft import Draft
from it_equipment.agent.handler import HandledRequest, handle_request
from it_equipment.agent.request import EquipmentRequest

PRIYAS_WORDS = "My laptop is 4 years old and slow, can I get a replacement?"
PRIYA_REQUEST = EquipmentRequest(employee_id="E001", text=PRIYAS_WORDS)

FLAG_ID = "5f0c6a8e-2b1d-4e7a-9c3f-8d2e1b0a7c64"

# What the fake server returns, shaped like the real tools' results.
PRIYA = {"employee_id": "E001", "name": "Priya Raman", "role": "standard"}

PRIYAS_LAPTOP = {
    "employee_id": "E001",
    "role": "standard",
    "item": "laptop",
    "held": 1,
    "max_quantity": 1,
    "refresh_years": 4,
    "additional": {"verdict": "denied", "reason": "One is held.", "next_eligible_on": None},
    "replacement": {"verdict": "approved", "reason": "It is due.", "next_eligible_on": None},
}

PRIYAS_FLAG = {"flag_id": FLAG_ID, "employee_id": "E001", "status": "queued"}

APPROVED = Draft(
    decision="approved",
    item="laptop",
    answered="replacement",
    message="Your request for a replacement laptop is approved.",
    reason="check_request_eligibility approved a replacement laptop for E001.",
    flag_id=None,
)

# The approval with its message corrected, as reflection might write it.
APPROVED_REWORDED = Draft(
    decision="approved",
    item="laptop",
    answered="replacement",
    message="Your replacement laptop is approved. IT will tell you which model you get.",
    reason="check_request_eligibility approved a replacement laptop for E001.",
    flag_id=None,
)

# Reflection's correction when it decides a person must look at the request:
# no verdict relayed, and no flag yet, as the reviewer prompt asks.
ESCALATED_BY_REFLECTION = Draft(
    decision="escalated",
    item="laptop",
    answered=None,
    message="A person will review your request for a replacement laptop.",
    reason="The request says the laptop is slow, which no tool can confirm.",
    flag_id=None,
)


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


def tool_call(tool_name: str, arguments: dict) -> Message:
    """A reply asking for one tool, with the thought the loop expects first."""
    with_thought = {"thought": "A reason."}
    for name in arguments:
        with_thought[name] = arguments[name]

    call = ToolUseBlock(type="tool_use", id="toolu_1", name=tool_name, input=with_thought)
    return model_reply([call], "tool_use")


def json_reply(fields: dict) -> Message:
    return model_reply([TextBlock(type="text", text=json.dumps(fields))], "end_turn")


def review(assessment: str, final: Draft) -> Message:
    fields = {
        "assessment": assessment,
        "problems": [],
        "checked": "The draft against every Observation.",
        "final": final.to_dict(),
    }
    if assessment == "revised":
        fields["problems"] = ["The message needs correcting, going by Observation 2."]

    return json_reply(fields)


def confirmed(draft: Draft) -> Message:
    return review("confirmed", draft)


def revised(final: Draft) -> Message:
    return review("revised", final)


def look_up_priya() -> Message:
    return tool_call("get_employee_info", {"employee_id": "E001"})


def check_laptop_for(employee_id: str) -> Message:
    return tool_call("check_request_eligibility", {"employee_id": employee_id, "item": "laptop"})


def flag_priya() -> Message:
    arguments = {"employee_id": "E001", "request": PRIYAS_WORDS, "reason": "A reason."}
    return tool_call("flag_for_human_review", arguments)


def priyas_loop(draft: Draft) -> list[Message]:
    """The loop's replies for Priya: look her up, check the laptop, then write the draft."""
    return [look_up_priya(), check_laptop_for("E001"), json_reply(draft.to_dict())]


def recorded(fields: dict) -> CallToolResult:
    text = json.dumps(fields, indent=2)
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=fields)


def refused(tool_name: str) -> CallToolResult:
    message = f"Error executing tool {tool_name}: \"No employee with id 'E999'\""
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


def priyas_server() -> FakeMcpClient:
    return FakeMcpClient(
        {
            "get_employee_info": recorded(PRIYA),
            "check_request_eligibility": recorded(PRIYAS_LAPTOP),
            "flag_for_human_review": recorded(PRIYAS_FLAG),
        }
    )


def flag_calls(mcp_client: FakeMcpClient) -> list[dict]:
    """The arguments of every flag_for_human_review call, the loop's and Python's, in order."""
    calls = []
    for name, arguments in mcp_client.calls:
        if name == "flag_for_human_review":
            calls.append(arguments)

    return calls


def handle(
    replies: list[Message],
    mcp_client: FakeMcpClient,
    request: EquipmentRequest = PRIYA_REQUEST,
    max_steps: int = 10,
) -> HandledRequest:
    model_client = ScriptedModelClient(replies)
    return asyncio.run(
        handle_request(model_client, mcp_client, "claude-opus-5", 16000, max_steps, request)
    )


def test_the_user_query_is_printed_first(capsys):
    handle(priyas_loop(APPROVED) + [confirmed(APPROVED)], priyas_server())

    printed = capsys.readouterr().out
    assert printed.startswith("User query\n  From:           E001\n")


def test_the_sections_are_printed_in_the_agreed_order(capsys):
    handle(priyas_loop(APPROVED) + [confirmed(APPROVED)], priyas_server())

    printed = capsys.readouterr().out
    assert printed.index("Step 1: ReAct loop") < printed.index("Draft after the ReAct loop")
    assert printed.index("Draft after the ReAct loop") < printed.index("Step 2: Reflection")
    assert printed.index("Step 2: Reflection") < printed.index("Step 3: Policy check (Python)")
    assert printed.index("Step 3: Policy check (Python)") < printed.index("Final answer")


def test_a_passed_check_is_printed_in_step_3_with_its_observation(capsys):
    handle(priyas_loop(APPROVED) + [confirmed(APPROVED)], priyas_server())

    printed = capsys.readouterr().out
    assert (
        "  Result:         Passed. The decision, approved, is the replacement verdict for laptop "
        "in\n                  Observation 2, for E001.\n"
    ) in printed


def test_a_confirmed_draft_that_passes_is_the_final_answer():
    handled = handle(priyas_loop(APPROVED) + [confirmed(APPROVED)], priyas_server())

    assert handled.final == APPROVED


def test_a_confirmed_draft_that_passes_is_not_flagged():
    mcp_client = priyas_server()

    handle(priyas_loop(APPROVED) + [confirmed(APPROVED)], mcp_client)

    assert flag_calls(mcp_client) == []


def test_a_revised_draft_that_passes_is_the_final_answer():
    handled = handle(priyas_loop(APPROVED) + [revised(APPROVED_REWORDED)], priyas_server())

    assert handled.final == APPROVED_REWORDED


def test_an_approval_never_carries_a_flag_id():
    """Only an escalated answer has a flag; an approval's flag id is the model's own invention."""
    with_a_flag_id = Draft(
        decision="approved",
        item="laptop",
        answered="replacement",
        message=APPROVED.message,
        reason=APPROVED.reason,
        flag_id="made-up-id",
    )

    handled = handle(priyas_loop(with_a_flag_id) + [confirmed(with_a_flag_id)], priyas_server())

    assert handled.final.flag_id is None


def test_an_escalation_by_reflection_is_flagged_with_the_employees_words_and_its_reason():
    mcp_client = priyas_server()

    handle(priyas_loop(APPROVED) + [revised(ESCALATED_BY_REFLECTION)], mcp_client)

    assert flag_calls(mcp_client) == [
        {
            "employee_id": "E001",
            "request": PRIYAS_WORDS,
            "reason": "The request says the laptop is slow, which no tool can confirm.",
        }
    ]


def test_an_escalation_by_reflection_ends_with_pythons_flag_id():
    handled = handle(priyas_loop(APPROVED) + [revised(ESCALATED_BY_REFLECTION)], priyas_server())

    assert handled.python_flag_id == FLAG_ID
    assert handled.final.flag_id == FLAG_ID


def test_an_approval_with_no_tool_calls_ends_escalated():
    """Guardrail G5: a model that approves without checking anything cannot have it stand."""
    replies = [json_reply(APPROVED.to_dict()), confirmed(APPROVED)]

    handled = handle(replies, priyas_server())

    assert handled.final.decision == "escalated"
    assert handled.final.reason == (
        "The Python check failed. The reviewed draft approves a replacement laptop, but no "
        "check_request_eligibility result for E001 in this run approves one."
    )


def test_an_approval_resting_on_another_employees_verdict_ends_escalated():
    """Guardrail G5: Priya's request cannot be approved on Daniel's laptop verdict."""
    daniels_laptop = dict(PRIYAS_LAPTOP)
    daniels_laptop["employee_id"] = "E002"
    mcp_client = priyas_server()
    mcp_client.results["check_request_eligibility"] = recorded(daniels_laptop)
    replies = [look_up_priya(), check_laptop_for("E002"), json_reply(APPROVED.to_dict())]

    handled = handle(replies + [confirmed(APPROVED)], mcp_client)

    assert handled.final.decision == "escalated"


def test_a_failed_check_ends_with_pythons_own_message():
    """The model's message may say "approved", so it is never sent once the check fails."""
    replies = [json_reply(APPROVED.to_dict()), confirmed(APPROVED)]

    handled = handle(replies, priyas_server())

    assert handled.final.message == (
        f"Your request has been passed to a person to review, under reference {FLAG_ID}. "
        "They will get back to you."
    )


def test_a_flag_the_loop_recorded_is_reused_when_the_check_fails():
    mcp_client = priyas_server()
    # The loop flags the request, then drafts an approval anyway.
    replies = [look_up_priya(), flag_priya(), json_reply(APPROVED.to_dict()), confirmed(APPROVED)]

    handled = handle(replies, mcp_client)

    assert len(flag_calls(mcp_client)) == 1
    assert handled.final.flag_id == FLAG_ID


def test_the_models_copy_of_a_flag_id_is_replaced_by_the_tools():
    escalated = Draft(
        decision="escalated",
        item="laptop",
        answered=None,
        message="A person will review your request.",
        reason="The request was flagged for a person.",
        flag_id="made-up-id",
    )
    replies = [look_up_priya(), flag_priya(), json_reply(escalated.to_dict()), confirmed(escalated)]

    handled = handle(replies, priyas_server())

    assert handled.final.flag_id == FLAG_ID


def test_a_run_with_no_draft_skips_reflection(capsys):
    handle([model_reply([], "refusal")], priyas_server())

    printed = capsys.readouterr().out
    assert "\nStep 2: Reflection\n  Reflection skipped: there is no draft to review.\n" in printed


def test_a_refusal_is_sent_to_a_person_by_python():
    mcp_client = priyas_server()

    handle([model_reply([], "refusal")], mcp_client)

    assert flag_calls(mcp_client) == [
        {
            "employee_id": "E001",
            "request": PRIYAS_WORDS,
            "reason": "The agent could not reach a decision: the model refused.",
        }
    ]


def test_a_run_with_no_draft_ends_with_step_3_and_pythons_answer(capsys):
    handle([model_reply([], "refusal")], priyas_server())

    printed = capsys.readouterr().out
    assert printed.endswith(
        "\n"
        "Step 3: Policy check (Python)\n"
        "  Result:         Not checked: there is no draft. Python sent the request to a person: "
        "flag id\n"
        "                  5f0c6a8e-2b1d-4e7a-9c3f-8d2e1b0a7c64.\n"
        "\n"
        "Final answer\n"
        "  Decision:       Escalated to a person\n"
        "  Flag id:        5f0c6a8e-2b1d-4e7a-9c3f-8d2e1b0a7c64\n"
        "  Reason:         The agent could not reach a decision: the model refused.\n"
        "  Message:        Your request has been passed to a person to review, under reference\n"
        "                  5f0c6a8e-2b1d-4e7a-9c3f-8d2e1b0a7c64. They will get back to you.\n"
    )


def test_a_reflection_refusal_is_sent_to_a_person_by_python():
    mcp_client = priyas_server()

    handle(priyas_loop(APPROVED) + [model_reply([], "refusal")], mcp_client)

    assert flag_calls(mcp_client)[0]["reason"] == (
        "The agent's draft could not be reviewed: the model refused."
    )


def test_the_step_limit_is_sent_to_a_person_by_python():
    mcp_client = priyas_server()

    handle([look_up_priya(), look_up_priya()], mcp_client, max_steps=2)

    assert flag_calls(mcp_client)[0]["reason"] == (
        "The agent could not reach a decision: it reached the limit of 2 calls to the model."
    )


def test_a_flag_the_loop_recorded_is_reused_when_there_is_no_draft():
    mcp_client = priyas_server()

    # The loop's one call flags the request, then the step limit ends it.
    handled = handle([flag_priya()], mcp_client, max_steps=1)

    assert len(flag_calls(mcp_client)) == 1
    assert handled.final.flag_id == FLAG_ID


def test_a_refused_python_flag_ends_not_processed():
    """Only an unknown id makes the flag tool refuse, so the employee is asked to check it."""
    unknown = EquipmentRequest(employee_id="E999", text="I need a new monitor.")
    mcp_client = FakeMcpClient({"flag_for_human_review": refused("flag_for_human_review")})

    handled = handle([model_reply([], "refusal")], mcp_client, request=unknown)

    assert handled.final.decision == "not_processed"
    assert handled.final.message == (
        "No employee has the id E999, so your request could not be processed. Please check your "
        "employee id and send the request again."
    )


def test_a_refused_flag_for_an_escalated_draft_ends_not_processed():
    """An escalated draft for an unknown id passes the check, then the tool refuses the flag."""
    unknown = EquipmentRequest(employee_id="E999", text="I need a new monitor.")
    escalated = Draft(
        decision="escalated",
        item="monitor",
        answered=None,
        message="A person will review your request.",
        reason="No employee has this id.",
        flag_id=None,
    )
    mcp_client = FakeMcpClient({"flag_for_human_review": refused("flag_for_human_review")})
    replies = [json_reply(escalated.to_dict()), confirmed(escalated)]

    handled = handle(replies, mcp_client, request=unknown)

    assert handled.final.decision == "not_processed"


def test_handle_request_returns_how_the_loop_ended():
    handled = handle([model_reply([], "refusal")], priyas_server())

    assert handled.loop.draft is None
    assert handled.loop.stopped_because == "the model refused"
