"""Unit tests for the logic behind the get_employee_info tool.

These call employee_info directly, as plain Python. They deliberately do not go
over HTTP and do not go through the MCP protocol, so a failure here points at
the logic rather than at the plumbing.

The date is passed in as a fixed constant rather than read from the clock,
which is what lets every expected tenure below be a constant.
"""

import json
from datetime import date

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from it_equipment.models import Employee, EquipmentItem
from it_equipment.repository import EmployeeRepository
from it_equipment.server import employee_info

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
            {"name": "laptop", "issued_on": "2022-03-01"},
            {"name": "monitor", "issued_on": "2022-03-01"},
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
