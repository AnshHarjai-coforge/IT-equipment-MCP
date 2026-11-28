"""Reflection's review of a draft: its shape, the schema that asks for it, and reading it back.

Reflection answers with one JSON object, held to REVIEW_SCHEMA by structured
output, as the draft is held to its own:

    assessment   "confirmed" when the draft is right as it stands, "revised"
                 when the review corrects it
    problems     each problem found, one sentence each; empty when confirmed
    checked      what the draft was checked against, in a sentence or two,
                 printed as the reason a confirmed draft holds
    final        the draft after the review, in the draft's own shape

reviewed_draft decides which draft goes on to the Python check. A confirmation
never changes anything, whatever final says.

The descriptions inside the schema are written for the model, as the draft's
are. It sits beside draft.py the way the review sits beside the draft: this
module reads the review, and reflection.py makes the call that asks for it.
"""

import json
from dataclasses import dataclass

from anthropic.types import Message

from it_equipment.agent.draft import (
    DRAFT_SCHEMA,
    Draft,
    InvalidDraftError,
    draft_from_fields,
    text_of_reply,
)

# The two answers a review can give. Written once, so the schema and the check
# in review_from_reply cannot differ.
ASSESSMENTS = ["confirmed", "revised"]

# Every field of a review, in the order the schema lists them.
REVIEW_FIELDS = ["assessment", "problems", "checked", "final"]

# Strict, as the draft's schema is: every field required and nothing else
# allowed. "final" is the draft's own schema, descriptions and all, so the loop
# and the reviewer read the same words about each of the six fields. The SDK's
# transform_schema leaves it unchanged, which a test checks.
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "assessment": {
            "enum": ASSESSMENTS,
            "description": (
                "confirmed when the draft is right as it stands; revised when final corrects it."
            ),
        },
        "problems": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Each problem with the draft, in one sentence naming the Action or Observation "
                "it rests on. Empty when the draft is confirmed."
            ),
        },
        "checked": {
            "type": "string",
            "description": "What you checked the draft against, in one or two sentences.",
        },
        "final": DRAFT_SCHEMA,
    },
    "additionalProperties": False,
    "required": REVIEW_FIELDS,
}

# What output_config's "format" is set to on the reflection call.
REVIEW_FORMAT = {"type": "json_schema", "schema": REVIEW_SCHEMA}


@dataclass(frozen=True)
class Review:
    """Reflection's answer: confirmed or revised, the problems it found, and its final draft."""

    assessment: str
    problems: list[str]
    checked: str
    final: Draft


class InvalidReviewError(Exception):
    """Raised when reflection's reply cannot be read as a review.

    The message says what was wrong with it, as InvalidDraftError's does.
    """


def review_from_reply(reply: Message) -> Review:
    """Return the review written in reflection's reply.

    Raises InvalidReviewError if the reply's text is not JSON, is not an
    object, lacks one of the four fields, has an assessment that is not
    allowed or problems that are not a list, or has a final that cannot be
    read as a draft.
    """
    try:
        fields = json.loads(text_of_reply(reply))
    except json.JSONDecodeError as error:
        raise InvalidReviewError(f"The reply's text is not JSON: {error}") from error

    if not isinstance(fields, dict):
        raise InvalidReviewError("The reply's text is JSON, but not an object.")

    for name in REVIEW_FIELDS:
        if name not in fields:
            raise InvalidReviewError(f"The review has no {name} field.")

    if fields["assessment"] not in ASSESSMENTS:
        assessment = fields["assessment"]
        raise InvalidReviewError(f"The assessment '{assessment}' is not one of {ASSESSMENTS}.")

    # Checked because the problems are printed one by one.
    if not isinstance(fields["problems"], list):
        raise InvalidReviewError("The review's problems are not a list.")

    # The final draft is checked by the same code as the loop's draft, so the
    # two cannot be held to different rules.
    try:
        final = draft_from_fields(fields["final"])
    except InvalidDraftError as error:
        raise InvalidReviewError(f"The review's final draft cannot be read: {error}") from error

    return Review(
        assessment=fields["assessment"],
        problems=fields["problems"],
        checked=fields["checked"],
        final=final,
    )


def reviewed_draft(draft: Draft, review: Review) -> Draft:
    """Return the draft that goes on to the Python check: the draft if confirmed, else final.

    A review that says "confirmed" but changes a field contradicts itself.
    Taking the draft as it was in that case means a confirmation can never
    quietly change anything.
    """
    if review.assessment == "confirmed":
        return draft

    return review.final
