"""Unit tests for the logic behind the MCP tools.

These call the plain functions directly, as plain Python. They deliberately do
not go over HTTP and do not go through the MCP protocol, so a failure here
points at the logic rather than at the plumbing.

The date is passed in as a fixed constant rather than read from the clock,
which is what lets every expected tenure below be a constant.
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from it_equipment.models import Employee, EquipmentItem, ItemAllowance, RolePolicy
from it_equipment.repository import EmployeeRepository, PolicyRepository
from it_equipment.review_queue import ReviewQueue
from it_equipment.server import employee_info, human_review, policy_limits, request_eligibility

# A fixed date, so every expected tenure below is a constant.
TODAY = date(2026, 11, 23)

# A fixed id and moment for review flags, in place of uuid4() and datetime.now().
FLAG_ID = "9b1d6c2e-4f7a-4c1e-8a3b-2d5e6f708192"
FLAGGED_AT = datetime(2026, 11, 23, 14, 3, 12, tzinfo=timezone.utc)

# An escalation the requirements name: a claim the records cannot confirm.
REQUEST = "I need a second monitor for a medical reason."
REASON = "The request claims a medical need, which the records cannot confirm."


@pytest.fixture
def repository() -> EmployeeRepository:
    """A one-employee repository built in memory, with no file involved."""
    priya = Employee(
        employee_id="E100",
        name="Priya Raman",
        role="standard",
        hire_date=date(2019, 4, 15),
        equipment=[
            EquipmentItem(name="laptop", issued_on=date(2022, 3, 1)),
            EquipmentItem(name="monitor", issued_on=date(2022, 3, 1)),
        ],
    )

    employees = {"E100": priya}
    return EmployeeRepository(employees)


def test_a_known_id_returns_the_record(repository):
    result = employee_info(repository, "E100", as_of=TODAY)

    assert result == {
        "employee_id": "E100",
        "name": "Priya Raman",
        "role": "standard",
        "tenure_years": 7,
        "equipment": [
            {"name": "laptop", "age_years": 4},
            {"name": "monitor", "age_years": 4},
        ],
    }


def test_an_unknown_id_raises_a_tool_error(repository):
    """ToolError, not EmployeeNotFoundError.

    The SDK only passes a ToolError's message on to the caller. Any other
    exception is replaced with a bare "Error executing tool get_employee_info",
    which would leave the agent unable to tell a missing employee from a bug.
    """
    with pytest.raises(ToolError):
        employee_info(repository, "E999", as_of=TODAY)


def test_the_tool_error_names_the_missing_id(repository):
    """The agent reads this message, so the id has to survive the translation."""
    with pytest.raises(ToolError) as raised:
        employee_info(repository, "E999", as_of=TODAY)

    assert "E999" in str(raised.value)


def test_the_result_is_json_serialisable(repository):
    """An MCP tool must return something that converts to JSON."""
    result = employee_info(repository, "E100", as_of=TODAY)

    # json.dumps raises TypeError if any value cannot be converted.
    as_json = json.dumps(result)

    assert json.loads(as_json) == result


@pytest.fixture
def policies() -> PolicyRepository:
    """A two-role policy repository built in memory, with no file involved."""
    standard = RolePolicy(
        role="standard",
        items=[
            ItemAllowance(item="laptop", max_quantity=1, refresh_years=4),
            ItemAllowance(item="monitor", max_quantity=1, refresh_years=3),
        ],
    )
    manager = RolePolicy(
        role="manager",
        items=[ItemAllowance(item="laptop", max_quantity=1, refresh_years=2)],
    )

    return PolicyRepository({"standard": standard, "manager": manager})


def test_a_known_role_returns_its_policy(policies):
    result = policy_limits(policies, "standard")

    assert result == {
        "role": "standard",
        "items": [
            {"item": "laptop", "max_quantity": 1, "refresh_years": 4},
            {"item": "monitor", "max_quantity": 1, "refresh_years": 3},
        ],
    }


def test_an_unknown_role_raises_a_tool_error(policies):
    """ToolError, not RoleNotFoundError, so the message reaches the agent."""
    with pytest.raises(ToolError):
        policy_limits(policies, "contractor")


def test_the_tool_error_names_the_role_and_lists_the_known_roles(policies):
    with pytest.raises(ToolError) as raised:
        policy_limits(policies, "contractor")

    message = str(raised.value)
    assert "contractor" in message
    assert "standard" in message
    assert "manager" in message


def test_the_policy_result_is_json_serialisable(policies):
    result = policy_limits(policies, "manager")

    as_json = json.dumps(result)

    assert json.loads(as_json) == result


@pytest.fixture
def employees_with_a_stray_role() -> EmployeeRepository:
    """Priya, plus an employee whose role the policies fixture doesn't cover."""
    priya = Employee(
        employee_id="E100",
        name="Priya Raman",
        role="standard",
        hire_date=date(2019, 4, 15),
        equipment=[
            EquipmentItem(name="laptop", issued_on=date(2022, 3, 1)),
            EquipmentItem(name="monitor", issued_on=date(2022, 3, 1)),
        ],
    )
    casey = Employee(
        employee_id="E400",
        name="Casey Doe",
        role="contractor",
        hire_date=date(2025, 1, 6),
        equipment=[],
    )

    return EmployeeRepository({"E100": priya, "E400": casey})


def test_eligibility_for_a_known_employee_returns_both_verdicts(
    employees_with_a_stray_role, policies
):
    result = request_eligibility(employees_with_a_stray_role, policies, "E100", "laptop", TODAY)

    assert result["employee_id"] == "E100"
    assert result["role"] == "standard"
    assert result["additional"]["verdict"] == "denied"
    assert result["replacement"]["verdict"] == "approved"


def test_eligibility_for_an_unknown_employee_raises_a_tool_error(
    employees_with_a_stray_role, policies
):
    with pytest.raises(ToolError) as raised:
        request_eligibility(employees_with_a_stray_role, policies, "E999", "laptop", TODAY)

    assert "E999" in str(raised.value)


def test_eligibility_for_a_role_with_no_policy_raises_a_tool_error(
    employees_with_a_stray_role, policies
):
    """The employee exists, but the question still cannot be answered."""
    with pytest.raises(ToolError) as raised:
        request_eligibility(employees_with_a_stray_role, policies, "E400", "laptop", TODAY)

    assert "contractor" in str(raised.value)


def test_a_denial_is_returned_normally_not_raised(employees_with_a_stray_role, policies):
    """Being outside policy is an answer, so it must not arrive as an error."""
    result = request_eligibility(employees_with_a_stray_role, policies, "E100", "monitor", TODAY)

    assert result["additional"]["verdict"] == "denied"


def test_needs_review_is_returned_normally_not_raised(employees_with_a_stray_role, policies):
    result = request_eligibility(
        employees_with_a_stray_role, policies, "E100", "standing desk", TODAY
    )

    assert result["additional"]["verdict"] == "needs_review"


def test_the_item_is_trimmed_and_lower_cased(employees_with_a_stray_role, policies):
    """ "Monitor " must not be mistaken for an item no policy covers."""
    result = request_eligibility(employees_with_a_stray_role, policies, "E100", "Monitor ", TODAY)

    assert result["item"] == "monitor"
    assert result["held"] == 1
    assert result["additional"]["verdict"] == "denied"


def test_the_eligibility_result_is_json_serialisable(employees_with_a_stray_role, policies):
    result = request_eligibility(employees_with_a_stray_role, policies, "E100", "laptop", TODAY)

    as_json = json.dumps(result)

    assert json.loads(as_json) == result


def read_lines(path: Path) -> list[str]:
    """Return the lines of a queue file, read directly rather than through the queue."""
    return path.read_text(encoding="utf-8").splitlines()


def test_a_flag_for_a_known_employee_is_returned_as_queued(repository, tmp_path):
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")

    result = human_review(repository, queue, "E100", REQUEST, REASON, FLAG_ID, FLAGGED_AT)

    assert result == {
        "flag_id": FLAG_ID,
        "employee_id": "E100",
        "request": REQUEST,
        "reason": REASON,
        "flagged_at": "2026-11-23T14:03:12+00:00",
        "status": "queued",
    }


def test_the_flag_is_written_to_the_queue_without_its_status(repository, tmp_path):
    """Being in the file is what queued means, so the file does not repeat it."""
    queue_file = tmp_path / "review_queue.jsonl"
    queue = ReviewQueue(queue_file)

    human_review(repository, queue, "E100", REQUEST, REASON, FLAG_ID, FLAGGED_AT)

    lines = read_lines(queue_file)
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "flag_id": FLAG_ID,
        "employee_id": "E100",
        "request": REQUEST,
        "reason": REASON,
        "flagged_at": "2026-11-23T14:03:12+00:00",
    }


def test_two_calls_make_two_flags(repository, tmp_path):
    """The tool is not idempotent: the same request flagged twice is two flags."""
    queue_file = tmp_path / "review_queue.jsonl"
    queue = ReviewQueue(queue_file)
    second_id = "0c5a7e31-2b6d-4f8e-9a1c-3d4b5e6f7a80"

    human_review(repository, queue, "E100", REQUEST, REASON, FLAG_ID, FLAGGED_AT)
    human_review(repository, queue, "E100", REQUEST, REASON, second_id, FLAGGED_AT)

    lines = read_lines(queue_file)
    assert len(lines) == 2
    assert json.loads(lines[0])["flag_id"] == FLAG_ID
    assert json.loads(lines[1])["flag_id"] == second_id


def test_a_flag_for_an_unknown_employee_raises_a_tool_error(repository, tmp_path):
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")

    with pytest.raises(ToolError) as raised:
        human_review(repository, queue, "E999", REQUEST, REASON, FLAG_ID, FLAGGED_AT)

    assert "E999" in str(raised.value)


def test_a_blank_request_raises_a_tool_error(repository, tmp_path):
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")

    with pytest.raises(ToolError) as raised:
        human_review(repository, queue, "E100", "", REASON, FLAG_ID, FLAGGED_AT)

    assert "request is blank" in str(raised.value)


def test_a_request_of_only_spaces_counts_as_blank(repository, tmp_path):
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")

    with pytest.raises(ToolError) as raised:
        human_review(repository, queue, "E100", "   ", REASON, FLAG_ID, FLAGGED_AT)

    assert "request is blank" in str(raised.value)


def test_a_blank_reason_raises_a_tool_error(repository, tmp_path):
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")

    with pytest.raises(ToolError) as raised:
        human_review(repository, queue, "E100", REQUEST, "", FLAG_ID, FLAGGED_AT)

    assert "reason is blank" in str(raised.value)


def test_a_reason_of_only_spaces_counts_as_blank(repository, tmp_path):
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")

    with pytest.raises(ToolError) as raised:
        human_review(repository, queue, "E100", REQUEST, "   ", FLAG_ID, FLAGGED_AT)

    assert "reason is blank" in str(raised.value)


def test_the_employee_is_checked_before_the_text(repository, tmp_path):
    """With an unknown id and a blank reason, the agent hears about the id first."""
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")

    with pytest.raises(ToolError) as raised:
        human_review(repository, queue, "E999", REQUEST, "", FLAG_ID, FLAGGED_AT)

    assert "E999" in str(raised.value)


def test_a_refused_flag_writes_nothing(repository, tmp_path):
    """A reviewer must never find a flag the agent was told had failed."""
    queue_file = tmp_path / "review_queue.jsonl"
    queue = ReviewQueue(queue_file)

    with pytest.raises(ToolError):
        human_review(repository, queue, "E999", REQUEST, REASON, FLAG_ID, FLAGGED_AT)
    with pytest.raises(ToolError):
        human_review(repository, queue, "E100", "", REASON, FLAG_ID, FLAGGED_AT)
    with pytest.raises(ToolError):
        human_review(repository, queue, "E100", REQUEST, "", FLAG_ID, FLAGGED_AT)

    assert not queue_file.exists()


def test_the_text_is_stored_exactly_as_passed(repository, tmp_path):
    """Blank is checked on trimmed text, but the employee's words are not altered."""
    queue_file = tmp_path / "review_queue.jsonl"
    queue = ReviewQueue(queue_file)

    human_review(repository, queue, "E100", "  " + REQUEST, REASON, FLAG_ID, FLAGGED_AT)

    assert json.loads(read_lines(queue_file)[0])["request"] == "  " + REQUEST


def test_the_flag_result_is_json_serialisable(repository, tmp_path):
    queue = ReviewQueue(tmp_path / "review_queue.jsonl")

    result = human_review(repository, queue, "E100", REQUEST, REASON, FLAG_ID, FLAGGED_AT)

    as_json = json.dumps(result)

    assert json.loads(as_json) == result
