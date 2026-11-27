"""The model's draft decision: its shape, the schema that asks for it, and reading it back.

The model ends the ReAct loop by writing its draft as JSON. The request asks
for it with output_config, whose format is DRAFT_SCHEMA, so the API holds the
model to that shape (structured output). Python then turns the text into a
Draft, so whatever comes next compares fields rather than reading prose.

The descriptions inside the schema are written for the model, the same way the
tools' docstrings are: they are what it reads when it fills in each field.
"""

import json
from dataclasses import dataclass

from anthropic.types import Message

# The values a decision may take, and the two verdicts a decision can relay.
# Written once, so the schema and the check in draft_from_reply cannot differ.
DECISIONS = ["approved", "denied", "escalated", "not_processed"]
ANSWERED = ["additional", "replacement"]

# Every field of a draft, in the order the schema lists them.
DRAFT_FIELDS = ["decision", "item", "answered", "message", "reason", "flag_id"]

# Written in the strict form structured output expects: every field required,
# no extra fields allowed, and "may be null" spelled as anyOf with null. The
# SDK's own transform_schema leaves it unchanged, which a test checks.
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "enum": DECISIONS,
            "description": (
                "approved or denied only as check_request_eligibility decided it; escalated "
                "once flag_for_human_review has recorded a flag; not_processed when no "
                "employee has the sender's id."
            ),
        },
        "item": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": (
                "The item the decision is about, in the catalogue's words (e.g. laptop), or "
                "null if it is unclear which item is meant."
            ),
        },
        "answered": {
            "anyOf": [{"enum": ANSWERED}, {"type": "null"}],
            "description": (
                "Which of check_request_eligibility's two verdicts the decision relays; null "
                "when the decision is escalated or not_processed."
            ),
        },
        "message": {
            "type": "string",
            "description": "The reply to the employee, in plain words.",
        },
        "reason": {
            "type": "string",
            "description": (
                "Why, in one or two sentences, naming the verdict or the flag the decision "
                "rests on."
            ),
        },
        "flag_id": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": (
                "The flag_id flag_for_human_review returned, when the decision is escalated; "
                "otherwise null."
            ),
        },
    },
    "additionalProperties": False,
    "required": DRAFT_FIELDS,
}

# What output_config's "format" is set to on every call to the model.
DRAFT_FORMAT = {"type": "json_schema", "schema": DRAFT_SCHEMA}


@dataclass(frozen=True)
class Draft:
    """The model's decision before anything checks it."""

    decision: str
    # None when it is unclear which item was meant.
    item: str | None
    # Which verdict the decision relays; None unless approved or denied.
    answered: str | None
    message: str
    reason: str
    # The flag the model recorded; None unless escalated.
    flag_id: str | None


class InvalidDraftError(Exception):
    """Raised when the model's final reply cannot be read as a draft.

    The message says what was wrong with it, so a test or a person reading the
    error can see why.
    """


def draft_from_reply(reply: Message) -> Draft:
    """Return the draft written in the model's final reply.

    Raises InvalidDraftError if the reply's text is not JSON, is not an object,
    lacks one of the six fields, or has a decision or an answered value that is
    not allowed. The API holds the model to the schema, but a reply cut short,
    or a model that ignored it, must not be mistaken for a decision.
    """
    texts = []
    for block in reply.content:
        # Thinking blocks are left out: the draft is what the model wrote, not
        # how it got there.
        if block.type == "text":
            texts.append(block.text)

    # Joined with nothing between them, so JSON that arrived in two pieces
    # reads as the one piece it was.
    text = "".join(texts)

    try:
        fields = json.loads(text)
    except json.JSONDecodeError as error:
        raise InvalidDraftError(f"The reply's text is not JSON: {error}") from error

    if not isinstance(fields, dict):
        raise InvalidDraftError("The reply's text is JSON, but not an object.")

    for name in DRAFT_FIELDS:
        if name not in fields:
            raise InvalidDraftError(f"The draft has no {name} field.")

    if fields["decision"] not in DECISIONS:
        decision = fields["decision"]
        raise InvalidDraftError(f"The decision '{decision}' is not one of {DECISIONS}.")

    # None is allowed here: an escalated or unprocessed request relays no verdict.
    if fields["answered"] is not None and fields["answered"] not in ANSWERED:
        answered = fields["answered"]
        raise InvalidDraftError(f"The answered value '{answered}' is not one of {ANSWERED}.")

    return Draft(
        decision=fields["decision"],
        item=fields["item"],
        answered=fields["answered"],
        message=fields["message"],
        reason=fields["reason"],
        flag_id=fields["flag_id"],
    )
