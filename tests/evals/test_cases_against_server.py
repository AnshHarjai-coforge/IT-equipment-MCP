"""The CI half of the eval harness: the server still gives every case the answers it needs.

For each committed case, each required call is made with the server's plain
function, as the tool would make it on the tests' fixed date, and its answer is
checked against what the case expects. A change to the employees or the
policies that would quietly break a demo answer then fails CI. For example,
case 1's check_request_eligibility("E001", "laptop") must still give the
replacement "approved".

The plain functions are called directly, never through the MCP protocol, so a
failure points at the data or the logic rather than the plumbing. The one test
that builds the server only reads the names of the tools it serves.
"""

import asyncio
from datetime import date, datetime, timezone
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from it_equipment.config import REPO_ROOT
from it_equipment.evals.cases import CASES_FILE, EvalCase, ToolCall, load_cases_from_json
from it_equipment.repository import load_employees_from_json, load_policies_from_json
from it_equipment.review_queue import ReviewQueue
from it_equipment.server import (
    build_server,
    employee_info,
    human_review,
    policy_limits,
    request_eligibility,
)

# A fixed date, so the answers cannot change with the calendar. The case
# file's verdicts are recorded as of this date.
TODAY = date(2026, 11, 23)

# A fixed id, moment and reason for a required flag, in place of the ones the
# tool would make. The case lists only the employee, so these fill the rest.
FLAG_ID = "3c9e2a71-5d84-4f06-b1e7-9a2c4d6e8f10"
FLAGGED_AT = datetime(2026, 11, 23, 14, 3, 12, tzinfo=timezone.utc)
FLAG_REASON = "The eval harness checks that this flag can be recorded."

COMMITTED_CASES = load_cases_from_json(CASES_FILE)
EMPLOYEES = load_employees_from_json(REPO_ROOT / "data" / "employees.json")
POLICIES = load_policies_from_json(REPO_ROOT / "data" / "policies.json")


def case_id_of(case: EvalCase) -> str:
    """Name each parametrized run after its case."""
    return case.case_id


def with_verdicts(cases: list[EvalCase]) -> list[EvalCase]:
    chosen = []
    for case in cases:
        if case.verdicts is not None:
            chosen.append(case)
    return chosen


def answer_to(call: ToolCall, case: EvalCase, queue: ReviewQueue) -> dict[str, Any]:
    """Make one tool call with the server's plain function, as the tool would on TODAY.

    A flag's request and reason are free text the case does not list, so the
    employee's own words and a fixed reason are passed.
    """
    arguments = call.arguments

    if call.tool == "get_employee_info":
        return employee_info(EMPLOYEES, arguments["employee_id"], as_of=TODAY)

    if call.tool == "get_policy_limits":
        return policy_limits(POLICIES, arguments["role"])

    if call.tool == "check_request_eligibility":
        return request_eligibility(
            EMPLOYEES, POLICIES, arguments["employee_id"], arguments["item"], as_of=TODAY
        )

    if call.tool == "flag_for_human_review":
        return human_review(
            EMPLOYEES,
            queue,
            arguments["employee_id"],
            case.request.text,
            FLAG_REASON,
            flag_id=FLAG_ID,
            flagged_at=FLAGGED_AT,
        )

    raise ValueError(f"No plain function is known for the tool {call.tool}.")


def check_answer_supports_the_case(call: ToolCall, case: EvalCase, queue: ReviewQueue) -> None:
    """Make one required call, and check its answer is the one the expected outcome rests on."""
    if case.expected.decision == "not_processed":
        # No employee has the sender's id, so the tool must refuse to answer:
        # that refusal is what not_processed rests on.
        with pytest.raises(ToolError):
            answer_to(call, case, queue)
        return

    answer = answer_to(call, case, queue)

    if call.tool == "get_employee_info":
        assert answer["employee_id"] == case.request.employee_id

    if call.tool == "check_request_eligibility":
        assert answer["additional"]["verdict"] == case.verdicts.additional
        assert answer["replacement"]["verdict"] == case.verdicts.replacement

    if call.tool == "flag_for_human_review":
        assert answer["status"] == "queued"


@pytest.mark.parametrize("case", COMMITTED_CASES, ids=case_id_of)
def test_the_required_calls_support_the_expected_outcome(case, tmp_path):
    """Every required call is made, in the case's order; any flag goes to tmp_path."""
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")

    for call in case.required_calls:
        check_answer_supports_the_case(call, case, queue)


@pytest.mark.parametrize("case", with_verdicts(COMMITTED_CASES), ids=case_id_of)
def test_the_recorded_verdicts_are_still_the_servers(case):
    """Also covers case 8, which requires no eligibility check but records what it would give."""
    answer = request_eligibility(
        EMPLOYEES, POLICIES, case.request.employee_id, case.expected.item, as_of=TODAY
    )

    assert answer["additional"]["verdict"] == case.verdicts.additional
    assert answer["replacement"]["verdict"] == case.verdicts.replacement


def test_every_tool_the_cases_name_is_one_the_server_serves(tmp_path):
    """A misspelled forbidden tool would otherwise pass every run without checking anything."""
    server = build_server(EMPLOYEES, POLICIES, ReviewQueue(tmp_path / "review_queue.jsonl"))

    listed = asyncio.run(server.list_tools())

    served = []
    for tool in listed:
        served.append(tool.name)
    for case in COMMITTED_CASES:
        for call in case.required_calls + case.forbidden_calls:
            assert call.tool in served, case.case_id
