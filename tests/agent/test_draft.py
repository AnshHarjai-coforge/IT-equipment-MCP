"""Unit tests for the draft: its schema, and reading it back from the model's reply.

Replies are real anthropic Message objects built from literals, shaped like
what the SDK returns. No model is called.
"""

import json

import pytest
from anthropic import transform_schema
from anthropic.types import Message, TextBlock, ThinkingBlock, Usage

from it_equipment.agent.draft import (
    DRAFT_FIELDS,
    DRAFT_FORMAT,
    DRAFT_SCHEMA,
    Draft,
    InvalidDraftError,
    draft_from_reply,
)

# Priya's laptop replacement, as the model would draft it.
APPROVED_REPLACEMENT = {
    "decision": "approved",
    "item": "laptop",
    "answered": "replacement",
    "message": "Your request for a replacement laptop is approved.",
    "reason": "check_request_eligibility approved a replacement laptop for E001.",
    "flag_id": None,
}


def reply_with_text(text: str) -> Message:
    return Message(
        id="msg_1",
        type="message",
        role="assistant",
        model="claude-opus-5",
        content=[TextBlock(type="text", text=text)],
        stop_reason="end_turn",
        stop_sequence=None,
        usage=Usage(input_tokens=100, output_tokens=50),
    )


def draft_with(**changes) -> str:
    """The approved draft as JSON text, with some fields changed or removed."""
    fields = dict(APPROVED_REPLACEMENT)
    for name in changes:
        if changes[name] == "REMOVE":
            del fields[name]
        else:
            fields[name] = changes[name]
    return json.dumps(fields)


def test_the_draft_in_a_reply_becomes_a_draft():
    reply = reply_with_text(json.dumps(APPROVED_REPLACEMENT))

    draft = draft_from_reply(reply)

    assert draft == Draft(
        decision="approved",
        item="laptop",
        answered="replacement",
        message="Your request for a replacement laptop is approved.",
        reason="check_request_eligibility approved a replacement laptop for E001.",
        flag_id=None,
    )


def test_null_fields_become_none():
    reply = reply_with_text(draft_with(decision="escalated", item=None, answered=None))

    draft = draft_from_reply(reply)

    assert draft.item is None
    assert draft.answered is None


def test_thinking_blocks_are_left_out_when_reading_the_draft():
    thinking = ThinkingBlock(type="thinking", thinking="", signature="sig")
    reply = reply_with_text(json.dumps(APPROVED_REPLACEMENT))
    reply.content.insert(0, thinking)

    draft = draft_from_reply(reply)

    assert draft.decision == "approved"


def test_text_that_is_not_json_raises_invalid_draft_error():
    reply = reply_with_text("Your laptop replacement is approved.")

    with pytest.raises(InvalidDraftError, match="not JSON"):
        draft_from_reply(reply)


def test_a_reply_with_no_text_raises_invalid_draft_error():
    reply = reply_with_text("")
    reply.content.clear()

    with pytest.raises(InvalidDraftError, match="not JSON"):
        draft_from_reply(reply)


def test_json_that_is_not_an_object_raises_invalid_draft_error():
    reply = reply_with_text('["approved"]')

    with pytest.raises(InvalidDraftError, match="not an object"):
        draft_from_reply(reply)


def test_a_missing_field_raises_and_names_the_field():
    reply = reply_with_text(draft_with(answered="REMOVE"))

    with pytest.raises(InvalidDraftError, match="no answered field"):
        draft_from_reply(reply)


def test_an_unknown_decision_raises_invalid_draft_error():
    reply = reply_with_text(draft_with(decision="maybe"))

    with pytest.raises(InvalidDraftError, match="'maybe'"):
        draft_from_reply(reply)


def test_an_unknown_answered_value_raises_invalid_draft_error():
    reply = reply_with_text(draft_with(answered="both"))

    with pytest.raises(InvalidDraftError, match="'both'"):
        draft_from_reply(reply)


def test_the_schema_requires_every_field_and_allows_no_others():
    assert list(DRAFT_SCHEMA["properties"].keys()) == DRAFT_FIELDS
    assert DRAFT_SCHEMA["required"] == DRAFT_FIELDS
    assert DRAFT_SCHEMA["additionalProperties"] is False


def test_the_schema_is_already_in_the_form_structured_output_expects():
    """The SDK's transform_schema rewrites anything structured output cannot use."""
    assert transform_schema(DRAFT_SCHEMA) == DRAFT_SCHEMA


def test_the_format_asks_for_json_matching_the_schema():
    assert DRAFT_FORMAT == {"type": "json_schema", "schema": DRAFT_SCHEMA}
