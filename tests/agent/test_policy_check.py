"""Unit tests for the Python check of the reviewed draft.

Every trace and draft here is a literal, with observations shaped like the
server's real results, so each rule is tested with no model and no server.
"""

import json
from dataclasses import replace

from it_equipment.agent.draft import Draft
from it_equipment.agent.policy_check import PolicyCheck, check_reviewed_draft
from it_equipment.agent.trace import TraceStep

FLAG_ID = "c242852e-a35e-4dc3-b1bc-c929d81a827f"

# Priya's laptop verdicts, as check_request_eligibility returns them.
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

APPROVED_REPLACEMENT = Draft(
    decision="approved",
    item="laptop",
    answered="replacement",
    message="Your replacement laptop is approved.",
    reason="check_request_eligibility approved a replacement laptop for E001.",
    flag_id=None,
)

ESCALATED = Draft(
    decision="escalated",
    item="laptop",
    answered=None,
    message="A person will review your request.",
    reason="The damage cannot be confirmed from the records.",
    flag_id=None,
)

NOT_PROCESSED = Draft(
    decision="not_processed",
    item="monitor",
    answered=None,
    message="Please check your employee id.",
    reason="No employee has the id E999.",
    flag_id=None,
)


def step(number: int, tool_name: str, arguments: dict, result: dict) -> TraceStep:
    return TraceStep(
        number=number,
        thought="",
        tool_name=tool_name,
        arguments=arguments,
        observation=json.dumps(result, indent=2),
        is_error=False,
    )


def refused(number: int, tool_name: str, arguments: dict) -> TraceStep:
    employee_id = arguments["employee_id"]
    message = f"Error executing tool {tool_name}: \"No employee with id '{employee_id}'\""
    return TraceStep(
        number=number,
        thought="",
        tool_name=tool_name,
        arguments=arguments,
        observation=message,
        is_error=True,
    )


def priyas_check(number: int = 2) -> TraceStep:
    arguments = {"employee_id": "E001", "item": "laptop"}
    return step(number, "check_request_eligibility", arguments, PRIYAS_LAPTOP)


def flag_for(number: int, employee_id: str) -> TraceStep:
    arguments = {"employee_id": employee_id, "request": "A request.", "reason": "A reason."}
    result = {"flag_id": FLAG_ID, "employee_id": employee_id, "status": "queued"}
    return step(number, "flag_for_human_review", arguments, result)


def test_an_approval_that_is_the_verdict_for_the_sender_passes():
    check = check_reviewed_draft("E001", [priyas_check()], APPROVED_REPLACEMENT)

    assert check == PolicyCheck(
        passed=True,
        explanation=(
            "The decision, approved, is the replacement verdict for laptop in Observation 2, "
            "for E001."
        ),
        flag_id=None,
    )


def test_a_denial_that_is_the_verdict_for_the_sender_passes():
    denied = replace(APPROVED_REPLACEMENT, decision="denied", answered="additional")

    check = check_reviewed_draft("E001", [priyas_check()], denied)

    assert check.passed is True


def test_an_approval_the_verdict_denies_fails():
    """Priya asked for a second laptop: the additional verdict denies it."""
    approved_additional = replace(APPROVED_REPLACEMENT, answered="additional")

    check = check_reviewed_draft("E001", [priyas_check()], approved_additional)

    assert check == PolicyCheck(
        passed=False,
        explanation=(
            "The reviewed draft approves an additional laptop, but no check_request_eligibility "
            "result for E001 in this run approves one."
        ),
        flag_id=None,
    )


def test_an_approval_with_no_tool_calls_fails():
    """Guardrail G5: a model that approves without calling any tool."""
    check = check_reviewed_draft("E001", [], APPROVED_REPLACEMENT)

    assert check.passed is False


def test_a_verdict_for_another_employee_is_no_evidence():
    """Guardrail G3: a request sent as E001 cannot rest on E002's verdict."""
    daniels = dict(PRIYAS_LAPTOP)
    daniels["employee_id"] = "E002"
    daniels_check = step(
        1, "check_request_eligibility", {"employee_id": "E002", "item": "laptop"}, daniels
    )

    check = check_reviewed_draft("E001", [daniels_check], APPROVED_REPLACEMENT)

    assert check.passed is False


def test_a_verdict_for_another_item_is_no_evidence():
    monitor = replace(APPROVED_REPLACEMENT, item="monitor")

    check = check_reviewed_draft("E001", [priyas_check()], monitor)

    assert check.passed is False


def test_the_drafts_item_is_trimmed_and_lower_cased_as_the_tool_does():
    capitalised = replace(APPROVED_REPLACEMENT, item=" Laptop ")

    check = check_reviewed_draft("E001", [priyas_check()], capitalised)

    assert check.passed is True


def test_an_approval_that_names_no_verdict_fails():
    no_answered = replace(APPROVED_REPLACEMENT, answered=None)

    check = check_reviewed_draft("E001", [priyas_check()], no_answered)

    assert check.explanation == (
        "The reviewed draft says approved, but does not name both the item and the verdict "
        "it relays."
    )


def test_an_eligibility_check_that_was_refused_is_no_evidence():
    refusal = refused(1, "check_request_eligibility", {"employee_id": "E001", "item": "laptop"})

    check = check_reviewed_draft("E001", [refusal], APPROVED_REPLACEMENT)

    assert check.passed is False


def test_an_escalation_with_a_flag_for_the_sender_passes_with_that_flag():
    check = check_reviewed_draft("E003", [priyas_check(), flag_for(3, "E003")], ESCALATED)

    assert check == PolicyCheck(
        passed=True,
        explanation="The decision is escalated, with the flag Observation 3 recorded for E003.",
        flag_id=FLAG_ID,
    )


def test_an_escalation_with_no_flag_yet_passes_with_none():
    check = check_reviewed_draft("E002", [], ESCALATED)

    assert check == PolicyCheck(
        passed=True,
        explanation="The decision is escalated, and no flag is recorded for E002 yet.",
        flag_id=None,
    )


def test_the_flag_id_comes_from_the_tool_not_from_the_draft():
    made_up = replace(ESCALATED, flag_id="made-up-id")

    check = check_reviewed_draft("E003", [flag_for(1, "E003")], made_up)

    assert check.flag_id == FLAG_ID


def test_a_flag_for_another_employee_is_not_this_requests_flag():
    check = check_reviewed_draft("E001", [flag_for(1, "E002")], ESCALATED)

    assert check.flag_id is None


def test_a_recorded_flag_with_a_decision_other_than_escalated_fails():
    """A person already has the request, so the answer cannot be decided here."""
    trace = [priyas_check(), flag_for(3, "E001")]

    check = check_reviewed_draft("E001", trace, APPROVED_REPLACEMENT)

    assert check == PolicyCheck(
        passed=False,
        explanation=(
            "Observation 3 recorded a flag for E001, so a person will review the request, "
            "but the reviewed draft says approved."
        ),
        flag_id=FLAG_ID,
    )


def test_not_processed_passes_when_the_lookup_refused_the_sender():
    lookup = refused(1, "get_employee_info", {"employee_id": "E999"})

    check = check_reviewed_draft("E999", [lookup], NOT_PROCESSED)

    assert check == PolicyCheck(
        passed=True,
        explanation="Observation 1 shows get_employee_info refused E999.",
        flag_id=None,
    )


def test_not_processed_fails_when_no_lookup_was_refused():
    lookup = step(1, "get_employee_info", {"employee_id": "E001"}, {"employee_id": "E001"})

    check = check_reviewed_draft("E001", [lookup], NOT_PROCESSED)

    assert check.explanation == (
        "The reviewed draft says not_processed, but no get_employee_info result in this run "
        "refused E001."
    )


def test_not_processed_fails_when_the_refused_lookup_was_for_another_id():
    lookup = refused(1, "get_employee_info", {"employee_id": "E999"})

    check = check_reviewed_draft("E001", [lookup], NOT_PROCESSED)

    assert check.passed is False
