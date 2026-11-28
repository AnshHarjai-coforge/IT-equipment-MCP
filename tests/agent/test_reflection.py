"""Unit tests for reflection: the message it is sent, the call it makes, and when it fails.

The model is a fake that hands back one real anthropic Message and records
what it was sent. No model is paid for and no server is involved: reflection
has no tools, so it never touches one. reflect is asynchronous, so each test
runs it with asyncio.run, from the standard library.
"""

import asyncio
import json

import pytest
from anthropic.types import Message, TextBlock, Usage

from it_equipment.agent.draft import Draft
from it_equipment.agent.prompts import REVIEWER_PROMPT
from it_equipment.agent.reflection import ReflectionFailedError, reflect, review_prompt_text
from it_equipment.agent.request import EquipmentRequest
from it_equipment.agent.review import REVIEW_FORMAT, Review
from it_equipment.agent.trace import TraceStep

PRIYA_REQUEST = EquipmentRequest(
    employee_id="E001",
    text="My laptop is 4 years old and slow, can I get a replacement?",
)

LOOK_UP = TraceStep(
    number=1,
    thought="I need her record first.",
    tool_name="get_employee_info",
    arguments={"employee_id": "E001"},
    observation='{\n  "employee_id": "E001",\n  "role": "standard"\n}',
    is_error=False,
)

CHECK = TraceStep(
    number=2,
    thought="She wants a new one in place of the old, so replacement applies.",
    tool_name="check_request_eligibility",
    arguments={"employee_id": "E001", "item": "laptop"},
    observation='{\n  "replacement": {\n    "verdict": "approved"\n  }\n}',
    is_error=False,
)

DRAFT = Draft(
    decision="approved",
    item="laptop",
    answered="replacement",
    message="Your replacement laptop is approved.",
    reason="check_request_eligibility approved a replacement laptop for E001.",
    flag_id=None,
)

CONFIRMED = {
    "assessment": "confirmed",
    "problems": [],
    "checked": "The decision against Observation 2's replacement verdict.",
    "final": DRAFT.to_dict(),
}


def model_reply(text: str, stop_reason: str = "end_turn") -> Message:
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-opus-5",
        content=[TextBlock(type="text", text=text)],
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=100, output_tokens=50),
    )


class OneReplyMessages:
    """Stands in for model_client.messages: records the call and hands back one reply."""

    def __init__(self, reply: Message) -> None:
        self.reply = reply
        self.requests = []

    async def create(self, **kwargs) -> Message:
        self.requests.append(kwargs)
        return self.reply


class FakeModelClient:
    def __init__(self, reply: Message) -> None:
        self.messages = OneReplyMessages(reply)


def run_reflect(model_client: FakeModelClient, trace: list[TraceStep] | None = None) -> Review:
    if trace is None:
        trace = [LOOK_UP, CHECK]
    return asyncio.run(reflect(model_client, "claude-opus-5", 16000, PRIYA_REQUEST, trace, DRAFT))


def test_the_message_holds_the_request_each_action_and_observation_and_the_draft():
    text = review_prompt_text(PRIYA_REQUEST, [LOOK_UP, CHECK], DRAFT)

    assert text == (
        "Employee E001 sent this request:\n"
        "\n"
        "<employee_request>\n"
        "My laptop is 4 years old and slow, can I get a replacement?\n"
        "</employee_request>\n"
        "\n"
        "The tool calls the agent made, in order, with exactly what each returned:\n"
        "\n"
        'Action 1: get_employee_info(employee_id="E001")\n'
        "Observation 1:\n"
        "{\n"
        '  "employee_id": "E001",\n'
        '  "role": "standard"\n'
        "}\n"
        "\n"
        'Action 2: check_request_eligibility(employee_id="E001", item="laptop")\n'
        "Observation 2:\n"
        "{\n"
        '  "replacement": {\n'
        '    "verdict": "approved"\n'
        "  }\n"
        "}\n"
        "\n"
        "The agent's draft:\n"
        "\n"
        "{\n"
        '  "decision": "approved",\n'
        '  "item": "laptop",\n'
        '  "answered": "replacement",\n'
        '  "message": "Your replacement laptop is approved.",\n'
        '  "reason": "check_request_eligibility approved a replacement laptop for E001.",\n'
        '  "flag_id": null\n'
        "}"
    )


def test_the_message_leaves_out_the_thoughts():
    text = review_prompt_text(PRIYA_REQUEST, [LOOK_UP, CHECK], DRAFT)

    assert LOOK_UP.thought not in text
    assert CHECK.thought not in text


def test_a_run_with_no_tool_calls_says_so():
    text = review_prompt_text(PRIYA_REQUEST, [], DRAFT)

    assert "\n\nThe agent made no tool calls.\n\nThe agent's draft:\n" in text


def test_reflection_sends_only_five_arguments_and_no_tools():
    model_client = FakeModelClient(model_reply(json.dumps(CONFIRMED)))

    run_reflect(model_client)

    sent = model_client.messages.requests[0]
    assert sorted(sent.keys()) == ["max_tokens", "messages", "model", "output_config", "system"]


def test_reflection_sends_the_reviewer_prompt_the_message_and_the_review_format():
    model_client = FakeModelClient(model_reply(json.dumps(CONFIRMED)))

    run_reflect(model_client)

    sent = model_client.messages.requests[0]
    assert sent["system"] == REVIEWER_PROMPT
    assert sent["messages"] == [
        {"role": "user", "content": review_prompt_text(PRIYA_REQUEST, [LOOK_UP, CHECK], DRAFT)}
    ]
    assert sent["output_config"] == {"format": REVIEW_FORMAT}


def test_reflection_sends_the_settings_passed_in():
    model_client = FakeModelClient(model_reply(json.dumps(CONFIRMED)))

    asyncio.run(reflect(model_client, "my-deployment", 4000, PRIYA_REQUEST, [], DRAFT))

    sent = model_client.messages.requests[0]
    assert sent["model"] == "my-deployment"
    assert sent["max_tokens"] == 4000


def test_reflection_returns_the_review_it_was_given():
    review = run_reflect(FakeModelClient(model_reply(json.dumps(CONFIRMED))))

    assert review.assessment == "confirmed"
    assert review.final == DRAFT


def test_a_refusal_raises_saying_the_model_refused():
    model_client = FakeModelClient(model_reply("", stop_reason="refusal"))

    with pytest.raises(ReflectionFailedError, match="^the model refused$"):
        run_reflect(model_client)


def test_a_reply_cut_off_at_max_tokens_raises_naming_the_limit():
    model_client = FakeModelClient(model_reply('{"assessment": "conf', stop_reason="max_tokens"))

    with pytest.raises(ReflectionFailedError, match="cut off at the limit of 16000 tokens"):
        run_reflect(model_client)


def test_a_reply_that_is_not_a_review_raises_saying_so():
    model_client = FakeModelClient(model_reply("The draft looks right to me."))

    with pytest.raises(ReflectionFailedError, match="could not be read as a review"):
        run_reflect(model_client)
