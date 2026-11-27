"""Unit tests for reflection's review: its schema, reading it back, and the draft it passes on.

Replies are real anthropic Message objects built from literals, shaped like
what the SDK returns. No model is called.
"""

import json
from dataclasses import replace

import pytest
from anthropic import transform_schema
from anthropic.types import Message, TextBlock, Usage

from it_equipment.agent.draft import DRAFT_SCHEMA, Draft
from it_equipment.agent.review import (
    REVIEW_FIELDS,
    REVIEW_FORMAT,
    REVIEW_SCHEMA,
    InvalidReviewError,
    Review,
    review_from_reply,
    reviewed_draft,
)

# Marcus's laptop, as the loop drafted it in the last live run.
MARCUS_DRAFT = Draft(
    decision="approved",
    item="laptop",
    answered="additional",
    message="Your laptop is approved. IT will arrange the handover.",
    reason="check_request_eligibility approved an additional laptop for E004.",
    flag_id=None,
)

# The same draft with the promise no tool confirmed taken out.
MARCUS_FINAL = replace(MARCUS_DRAFT, message="Your laptop is approved.")

REVISED = {
    "assessment": "revised",
    "problems": ["The message promises a handover that no tool confirmed."],
    "checked": "The decision against Observation 2, and each promise in the message.",
    "final": {
        "decision": "approved",
        "item": "laptop",
        "answered": "additional",
        "message": "Your laptop is approved.",
        "reason": "check_request_eligibility approved an additional laptop for E004.",
        "flag_id": None,
    },
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


def review_with(**changes) -> str:
    """The revised review as JSON text, with some fields changed or removed."""
    fields = dict(REVISED)
    for name in changes:
        if changes[name] == "REMOVE":
            del fields[name]
        else:
            fields[name] = changes[name]
    return json.dumps(fields)


def test_the_review_in_a_reply_becomes_a_review_with_a_final_draft():
    review = review_from_reply(reply_with_text(json.dumps(REVISED)))

    assert review == Review(
        assessment="revised",
        problems=["The message promises a handover that no tool confirmed."],
        checked="The decision against Observation 2, and each promise in the message.",
        final=MARCUS_FINAL,
    )


def test_text_that_is_not_json_raises_invalid_review_error():
    with pytest.raises(InvalidReviewError, match="not JSON"):
        review_from_reply(reply_with_text("The draft looks right."))


def test_json_that_is_not_an_object_raises_invalid_review_error():
    with pytest.raises(InvalidReviewError, match="not an object"):
        review_from_reply(reply_with_text('["confirmed"]'))


def test_a_missing_field_raises_and_names_the_field():
    with pytest.raises(InvalidReviewError, match="no checked field"):
        review_from_reply(reply_with_text(review_with(checked="REMOVE")))


def test_an_unknown_assessment_raises_invalid_review_error():
    with pytest.raises(InvalidReviewError, match="'unsure'"):
        review_from_reply(reply_with_text(review_with(assessment="unsure")))


def test_problems_that_are_not_a_list_raise_invalid_review_error():
    with pytest.raises(InvalidReviewError, match="not a list"):
        review_from_reply(reply_with_text(review_with(problems="One problem.")))


def test_a_final_that_is_not_a_draft_raises_and_says_why():
    final = dict(REVISED["final"])
    final["decision"] = "maybe"

    with pytest.raises(InvalidReviewError, match="final draft cannot be read.*'maybe'"):
        review_from_reply(reply_with_text(review_with(final=final)))


def test_a_confirmed_review_passes_on_the_draft_even_if_final_differs():
    review = Review(assessment="confirmed", problems=[], checked="", final=MARCUS_FINAL)

    assert reviewed_draft(MARCUS_DRAFT, review) == MARCUS_DRAFT


def test_a_revised_review_passes_on_its_final_draft():
    review = Review(assessment="revised", problems=["A problem."], checked="", final=MARCUS_FINAL)

    assert reviewed_draft(MARCUS_DRAFT, review) == MARCUS_FINAL


def test_the_schema_requires_every_field_and_allows_no_others():
    assert list(REVIEW_SCHEMA["properties"].keys()) == REVIEW_FIELDS
    assert REVIEW_SCHEMA["required"] == REVIEW_FIELDS
    assert REVIEW_SCHEMA["additionalProperties"] is False


def test_the_final_draft_has_the_drafts_own_schema():
    assert REVIEW_SCHEMA["properties"]["final"] == DRAFT_SCHEMA


def test_the_schema_is_already_in_the_form_structured_output_expects():
    """The SDK's transform_schema rewrites anything structured output cannot use."""
    assert transform_schema(REVIEW_SCHEMA) == REVIEW_SCHEMA


def test_the_format_asks_for_json_matching_the_schema():
    assert REVIEW_FORMAT == {"type": "json_schema", "schema": REVIEW_SCHEMA}
