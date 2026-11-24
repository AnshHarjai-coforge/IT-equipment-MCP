"""Unit tests for EmployeeRepository and PolicyRepository, called directly as plain Python.

These tests deliberately do not go through the MCP protocol. They check the
logic the tool will wrap, so a failure points at the logic and not the plumbing.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from it_equipment.models import Employee, EquipmentItem, ItemAllowance, RolePolicy
from it_equipment.repository import (
    EmployeeNotFoundError,
    EmployeeRepository,
    PolicyRepository,
    RoleNotFoundError,
    load_employees_from_json,
    load_policies_from_json,
)

# The committed mock data. __file__ is this test file, so its parent is tests/
# and the parent of that is the repository root.
DATA_FILE = Path(__file__).parent.parent / "data" / "employees.json"
POLICIES_FILE = Path(__file__).parent.parent / "data" / "policies.json"

# A fixed date, so every expected tenure below is a constant.
TODAY = date(2026, 11, 23)


@pytest.fixture
def repository() -> EmployeeRepository:
    """A two-employee repository built in memory, with no file involved."""
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
    marcus = Employee(
        employee_id="E200",
        name="Marcus Webb",
        role="standard",
        hire_date=date(2026, 11, 2),
        equipment=[],
    )

    employees = {"E100": priya, "E200": marcus}
    return EmployeeRepository(employees)


def test_returns_the_record_of_a_known_employee(repository):
    employee = repository.get_employee("E100")

    assert employee.employee_id == "E100"
    assert employee.name == "Priya Raman"
    assert employee.role == "standard"
    assert employee.hire_date == date(2019, 4, 15)


def test_returns_the_equipment_on_file(repository):
    employee = repository.get_employee("E100")

    assert employee.equipment == [
        EquipmentItem(name="laptop", issued_on=date(2022, 3, 1)),
        EquipmentItem(name="monitor", issued_on=date(2022, 3, 1)),
    ]


def test_employee_with_no_equipment_has_an_empty_list(repository):
    employee = repository.get_employee("E200")

    assert employee.equipment == []


def test_unknown_employee_id_raises(repository):
    with pytest.raises(EmployeeNotFoundError):
        repository.get_employee("E999")


def test_the_tool_result_is_json_serialisable(repository):
    """An MCP tool must return something that converts to JSON."""
    result = repository.get_employee("E100").to_dict(as_of=TODAY)

    # json.dumps raises TypeError if any value cannot be converted.
    as_json = json.dumps(result)

    assert json.loads(as_json) == result


def test_loading_from_json_converts_the_dates(tmp_path):
    record = {
        "employee_id": "E300",
        "name": "Sofia Brandt",
        "role": "engineer",
        "hire_date": "2015-01-12",
        "equipment": [{"name": "laptop", "issued_on": "2025-08-20"}],
    }
    path = tmp_path / "employees.json"
    path.write_text(json.dumps([record]), encoding="utf-8")

    repository = load_employees_from_json(path)
    employee = repository.get_employee("E300")

    assert employee.role == "engineer"
    # The text in the file has become real date objects.
    assert employee.hire_date == date(2015, 1, 12)
    assert employee.equipment[0].issued_on == date(2025, 8, 20)


def test_the_committed_data_file_loads():
    """A typo in data/employees.json should fail CI, not a live demo."""
    repository = load_employees_from_json(DATA_FILE)

    employee = repository.get_employee("E001")

    assert employee.role == "standard"
    assert employee.tenure_years(as_of=TODAY) == 7


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
    engineer = RolePolicy(
        role="engineer",
        items=[
            ItemAllowance(item="laptop", max_quantity=1, refresh_years=3),
            ItemAllowance(item="docking station", max_quantity=1, refresh_years=4),
        ],
    )

    return PolicyRepository({"standard": standard, "engineer": engineer})


def test_returns_the_policy_for_a_known_role(policies):
    policy = policies.get_policy("standard")

    assert policy.role == "standard"
    assert policy.items[1] == ItemAllowance(item="monitor", max_quantity=1, refresh_years=3)


def test_unknown_role_raises(policies):
    with pytest.raises(RoleNotFoundError):
        policies.get_policy("contractor")


def test_the_unknown_role_message_lists_the_known_roles(policies):
    """Whoever reads the message can see what was expected, not only what was wrong."""
    with pytest.raises(RoleNotFoundError) as raised:
        policies.get_policy("contractor")

    message = str(raised.value)
    assert "contractor" in message
    assert "standard" in message
    assert "engineer" in message


def test_roles_are_matched_exactly(policies):
    """A near miss is not quietly treated as the role it resembles."""
    with pytest.raises(RoleNotFoundError):
        policies.get_policy("Standard")


def test_the_catalogue_lists_every_item_once(policies):
    # The laptop appears under both roles but is listed once, in first-seen order.
    assert policies.catalogue() == ["laptop", "monitor", "docking station"]


def test_loading_policies_from_json(tmp_path):
    record = {
        "role": "manager",
        "items": [{"item": "laptop", "max_quantity": 1, "refresh_years": 2}],
    }
    path = tmp_path / "policies.json"
    path.write_text(json.dumps([record]), encoding="utf-8")

    policies = load_policies_from_json(path)

    assert policies.get_policy("manager") == RolePolicy(
        role="manager",
        items=[ItemAllowance(item="laptop", max_quantity=1, refresh_years=2)],
    )


def test_the_committed_policies_file_holds_the_agreed_rules():
    """A typo in data/policies.json should fail CI, not a live demo.

    The whole table is asserted, so any change to what the system approves has
    to be made here as well, on purpose.
    """
    policies = load_policies_from_json(POLICIES_FILE)

    assert policies.get_policy("standard").to_dict() == {
        "role": "standard",
        "items": [
            {"item": "laptop", "max_quantity": 1, "refresh_years": 4},
            {"item": "monitor", "max_quantity": 1, "refresh_years": 3},
        ],
    }
    assert policies.get_policy("engineer").to_dict() == {
        "role": "engineer",
        "items": [
            {"item": "laptop", "max_quantity": 1, "refresh_years": 3},
            {"item": "monitor", "max_quantity": 2, "refresh_years": 4},
            {"item": "docking station", "max_quantity": 1, "refresh_years": 4},
        ],
    }
    assert policies.get_policy("manager").to_dict() == {
        "role": "manager",
        "items": [
            {"item": "laptop", "max_quantity": 1, "refresh_years": 2},
            {"item": "monitor", "max_quantity": 2, "refresh_years": 3},
            {"item": "docking station", "max_quantity": 1, "refresh_years": 4},
        ],
    }
    assert policies.catalogue() == ["laptop", "monitor", "docking station"]


def test_every_employee_role_has_a_policy():
    """An employee whose role has no policy could never have a request checked."""
    policies = load_policies_from_json(POLICIES_FILE)
    # The raw records are read here only to find every role in use. The
    # repository has no "list all employees" method, and the tool code has no
    # reason to need one.
    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    for record in records:
        # Raises RoleNotFoundError, and so fails the test, for a missing role.
        policies.get_policy(record["role"])
