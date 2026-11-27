"""Unit tests for the eval cases: reading them, and the committed file agreeing with itself.

The first tests build cases from literal records, with no file or from a file
in pytest's tmp_path. The rest load the committed data/eval_cases.json, so a
typo in it fails CI rather than an eval run.

Checks that hold for every committed case are run once per case with
pytest.mark.parametrize, which repeats a test for each item of a list. Each run
is named after its case, e.g. test_...[3-escalated-no-policy], so a failure
says which case broke.
"""

import json

import pytest

from it_equipment.agent.draft import ANSWERED, DECISIONS
from it_equipment.agent.request import EquipmentRequest
from it_equipment.eligibility import APPROVED, DENIED, NEEDS_REVIEW
from it_equipment.evals.cases import (
    CASES_FILE,
    EvalCase,
    ExpectedOutcome,
    ExpectedVerdicts,
    ToolCall,
    build_case,
    load_cases_from_json,
)

# Demo request 2, as a record in the case file.
SECOND_MONITOR = {
    "case_id": "2-denied-second-monitor",
    "summary": "Denied: standard employees hold at most 1 monitor.",
    "employee_id": "E001",
    "request": "I need a second monitor.",
    "expected": {
        "decision": "denied",
        "item": "monitor",
        "answered": "additional",
        "flagged": False,
    },
    "verdicts": {"additional": "denied", "replacement": "approved"},
    "required_calls": [{"tool": "get_employee_info", "arguments": {"employee_id": "E001"}}],
    "forbidden_calls": [{"tool": "flag_for_human_review", "arguments": {}}],
}


def case_id_of(case: EvalCase) -> str:
    """Name each parametrized run after its case."""
    return case.case_id


def approved_or_denied(cases: list[EvalCase]) -> list[EvalCase]:
    chosen = []
    for case in cases:
        if case.expected.decision in [APPROVED, DENIED]:
            chosen.append(case)
    return chosen


def with_verdicts(cases: list[EvalCase]) -> list[EvalCase]:
    chosen = []
    for case in cases:
        if case.verdicts is not None:
            chosen.append(case)
    return chosen


COMMITTED_CASES = load_cases_from_json(CASES_FILE)


def test_a_record_becomes_a_case():
    case = build_case(SECOND_MONITOR)

    assert case == EvalCase(
        case_id="2-denied-second-monitor",
        summary="Denied: standard employees hold at most 1 monitor.",
        request=EquipmentRequest(employee_id="E001", text="I need a second monitor."),
        expected=ExpectedOutcome(
            decision="denied", item="monitor", answered="additional", flagged=False
        ),
        verdicts=ExpectedVerdicts(additional="denied", replacement="approved"),
        required_calls=[ToolCall(tool="get_employee_info", arguments={"employee_id": "E001"})],
        forbidden_calls=[ToolCall(tool="flag_for_human_review", arguments={})],
    )


def test_null_verdicts_become_none():
    """How the file says no employee has the id."""
    record = dict(SECOND_MONITOR)
    record["verdicts"] = None

    case = build_case(record)

    assert case.verdicts is None


def test_cases_load_in_the_files_order(tmp_path):
    first = dict(SECOND_MONITOR)
    first["case_id"] = "first"
    second = dict(SECOND_MONITOR)
    second["case_id"] = "second"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([first, second]), encoding="utf-8")

    cases = load_cases_from_json(path)

    assert [cases[0].case_id, cases[1].case_id] == ["first", "second"]


def test_a_record_missing_a_field_raises_key_error():
    record = dict(SECOND_MONITOR)
    del record["forbidden_calls"]

    with pytest.raises(KeyError):
        build_case(record)


def test_the_committed_file_holds_the_eight_demo_requests_in_order():
    case_ids = []
    for case in COMMITTED_CASES:
        case_ids.append(case.case_id)

    assert case_ids == [
        "1-approved-replacement",
        "2-denied-second-monitor",
        "3-escalated-no-policy",
        "4-escalated-damage-claim",
        "5-not-processed-unknown-id",
        "6-approved-new-starter",
        "7-denied-second-macbook",
        "8-escalated-injection",
    ]


@pytest.mark.parametrize("case", COMMITTED_CASES, ids=case_id_of)
def test_each_expected_decision_is_one_a_draft_can_give(case):
    assert case.expected.decision in DECISIONS


@pytest.mark.parametrize("case", COMMITTED_CASES, ids=case_id_of)
def test_a_case_expects_a_relayed_verdict_exactly_when_approved_or_denied(case):
    """The draft's rule: answered is null when the decision is escalated or not_processed."""
    relays_a_verdict = case.expected.decision in [APPROVED, DENIED]

    if relays_a_verdict:
        assert case.expected.answered in ANSWERED
    else:
        assert case.expected.answered is None


@pytest.mark.parametrize("case", COMMITTED_CASES, ids=case_id_of)
def test_a_case_expects_a_flag_exactly_when_it_is_escalated(case):
    assert case.expected.flagged == (case.expected.decision == "escalated")


@pytest.mark.parametrize("case", COMMITTED_CASES, ids=case_id_of)
def test_a_case_has_no_verdicts_exactly_when_it_is_not_processed(case):
    """With no employee there is nothing to check, and otherwise there always is."""
    assert (case.verdicts is None) == (case.expected.decision == "not_processed")


@pytest.mark.parametrize("case", with_verdicts(COMMITTED_CASES), ids=case_id_of)
def test_each_recorded_verdict_is_one_the_check_can_give(case):
    assert case.verdicts.additional in [APPROVED, DENIED, NEEDS_REVIEW]
    assert case.verdicts.replacement in [APPROVED, DENIED, NEEDS_REVIEW]


@pytest.mark.parametrize("case", approved_or_denied(COMMITTED_CASES), ids=case_id_of)
def test_an_approved_or_denied_case_relays_its_recorded_verdict(case):
    """Otherwise the case would expect a decision its own verdicts do not give."""
    if case.expected.answered == "additional":
        relayed = case.verdicts.additional
    else:
        relayed = case.verdicts.replacement

    assert relayed == case.expected.decision
