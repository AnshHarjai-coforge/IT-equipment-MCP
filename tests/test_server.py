"""Unit tests for the logic behind the MCP tools.

These call the plain functions directly, as plain Python. They deliberately do
not go over HTTP and do not go through the MCP protocol, so a failure here
points at the logic rather than at the plumbing.

The date is passed in as a fixed constant rather than read from the clock,
which is what lets every expected tenure below be a constant.
"""

import json
from datetime import date

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from it_equipment.models import Employee, EquipmentItem, ItemAllowance, RolePolicy
from it_equipment.repository import EmployeeRepository, PolicyRepository
from it_equipment.server import employee_info, policy_limits

# A fixed date, so every expected tenure below is a constant.
TODAY = date(2026, 11, 23)


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
