"""The Python check: the last word on the reviewed draft, which no wording can get past.

In plain words, in this order:

    1. If this run recorded a flag for the sender, the decision must be
       escalated. A person already has the request in the queue, and the
       model may move a decision only towards a person (plan decision 9).
    2. Escalated passes. Its flag is the one this run recorded for the
       sender; if there is none yet, the caller makes one.
    3. Approved or denied must be the verdict named by item and answered in
       a check_request_eligibility result from this run for the sender
       (guardrail G3), so an answer can rest neither on another employee's
       verdict nor on no verdict at all.
    4. Not processed needs get_employee_info to have refused the sender's id.

A draft that fails is sent to a person by the caller. Everything here is pure:
it reads the trace and the draft and returns a PolicyCheck, so each rule is
tested with literal drafts and traces, and no model or server.
"""

import json
from dataclasses import dataclass

from it_equipment.agent.draft import Draft
from it_equipment.agent.trace import TraceStep

LOOKUP_TOOL = "get_employee_info"
CHECK_TOOL = "check_request_eligibility"
FLAG_TOOL = "flag_for_human_review"


@dataclass(frozen=True)
class PolicyCheck:
    """What the Python check found: whether the draft stands, why, and any flag already recorded."""

    passed: bool
    # A sentence saying why, naming the Observation the decision rests on,
    # e.g. "The decision, approved, is the replacement verdict for laptop in
    # Observation 2, for E001."
    explanation: str
    # The flag this run recorded for the sender, or None if it recorded none.
    # Taken from the tool's own result, never from the model's draft.
    flag_id: str | None


def check_reviewed_draft(employee_id: str, trace: list[TraceStep], draft: Draft) -> PolicyCheck:
    """Return whether the reviewed draft stands, checked against this run's tool results."""
    flag_step = first_flag_step_for(employee_id, trace)
    flag_id = recorded_flag_id(employee_id, trace)

    if flag_step is not None and draft.decision != "escalated":
        return PolicyCheck(
            passed=False,
            explanation=(
                f"Observation {flag_step.number} recorded a flag for {employee_id}, so a person "
                f"will review the request, but the reviewed draft says {draft.decision}."
            ),
            flag_id=flag_id,
        )

    if draft.decision == "escalated":
        if flag_step is None:
            return PolicyCheck(
                passed=True,
                explanation=(
                    f"The decision is escalated, and no flag is recorded for {employee_id} yet."
                ),
                flag_id=None,
            )

        return PolicyCheck(
            passed=True,
            explanation=(
                f"The decision is escalated, with the flag Observation {flag_step.number} "
                f"recorded for {employee_id}."
            ),
            flag_id=flag_id,
        )

    if draft.decision == "not_processed":
        return not_processed_check(employee_id, trace)

    return verdict_check(employee_id, trace, draft)


def verdict_check(employee_id: str, trace: list[TraceStep], draft: Draft) -> PolicyCheck:
    """Return whether an approved or denied draft is a verdict this run gave for the sender."""
    if draft.item is None or draft.answered is None:
        return PolicyCheck(
            passed=False,
            explanation=(
                f"The reviewed draft says {draft.decision}, but does not name both the item "
                "and the verdict it relays."
            ),
            flag_id=None,
        )

    # The tool trims and lower-cases the item before looking it up, and
    # reports it that way, so the draft's item is compared the same way.
    item = draft.item.strip().lower()

    for step in trace:
        if step.tool_name != CHECK_TOOL or step.is_error:
            continue

        result = json.loads(step.observation)

        # A verdict for anyone else, or for another item, is no evidence for
        # this answer (G3: a request sent as E001 cannot rest on E002's).
        if result["employee_id"] != employee_id or result["item"] != item:
            continue

        if result[draft.answered]["verdict"] == draft.decision:
            return PolicyCheck(
                passed=True,
                explanation=(
                    f"The decision, {draft.decision}, is the {draft.answered} verdict for "
                    f"{item} in Observation {step.number}, for {employee_id}."
                ),
                flag_id=None,
            )

    verb = "approves"
    if draft.decision == "denied":
        verb = "denies"

    article = "a"
    if draft.answered == "additional":
        article = "an"

    return PolicyCheck(
        passed=False,
        explanation=(
            f"The reviewed draft {verb} {article} {draft.answered} {item}, but no "
            f"{CHECK_TOOL} result for {employee_id} in this run {verb} one."
        ),
        flag_id=None,
    )


def not_processed_check(employee_id: str, trace: list[TraceStep]) -> PolicyCheck:
    """Return whether get_employee_info refused the sender's id, which not_processed rests on."""
    for step in trace:
        if step.tool_name == LOOKUP_TOOL and step.is_error and is_for(employee_id, step):
            return PolicyCheck(
                passed=True,
                explanation=f"Observation {step.number} shows {LOOKUP_TOOL} refused {employee_id}.",
                flag_id=None,
            )

    return PolicyCheck(
        passed=False,
        explanation=(
            f"The reviewed draft says not_processed, but no {LOOKUP_TOOL} result in this run "
            f"refused {employee_id}."
        ),
        flag_id=None,
    )


def recorded_flag_id(employee_id: str, trace: list[TraceStep]) -> str | None:
    """Return the id of the first flag this run recorded for the employee, or None if none.

    Read from the tool's own result, so the id is one the server really made.
    Python uses it rather than making a second flag for the same request.
    """
    flag_step = first_flag_step_for(employee_id, trace)
    if flag_step is None:
        return None

    return json.loads(flag_step.observation)["flag_id"]


def first_flag_step_for(employee_id: str, trace: list[TraceStep]) -> TraceStep | None:
    """Return the first step that recorded a flag for this employee, or None if none did.

    A refused flag records nothing, and a flag for another employee is not a
    flag for this request, so neither counts.
    """
    for step in trace:
        if step.tool_name != FLAG_TOOL or step.is_error:
            continue

        # A recorded flag's observation is the tool's dictionary as JSON,
        # which names the employee the flag was recorded for.
        recorded = json.loads(step.observation)
        if recorded["employee_id"] == employee_id:
            return step

    return None


def is_for(employee_id: str, step: TraceStep) -> bool:
    """Return True when the step's tool call was for this employee id."""
    if "employee_id" not in step.arguments:
        return False

    return step.arguments["employee_id"] == employee_id
