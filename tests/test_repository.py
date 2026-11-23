"""Unit tests for EmployeeRepository, called directly as plain Python.

These tests deliberately do not go through the MCP protocol. They check the
logic the tool will wrap, so a failure points at the logic and not the plumbing.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from it_equipment.models import Employee, EquipmentItem
from it_equipment.repository import EmployeeNotFoundError, EmployeeRepository

# The committed mock data, two directories up from this file.
DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "employees.json"

# A fixed date, so every expected tenure below is a constant.
TODAY = date(2026, 11, 23)


@pytest.fixture
def repository() -> EmployeeRepository:
    """A two-employee repository built in memory, with no file involved."""
    return EmployeeRepository(
        {
            "E100": Employee(
                employee_id="E100",
                name="Priya Raman",
                role="standard",
                hire_date=date(2019, 4, 15),
                equipment=(
                    EquipmentItem(name="laptop", issued_on=date(2022, 3, 1)),
                    EquipmentItem(name="monitor", issued_on=date(2022, 3, 1)),
                ),
            ),
            "E200": Employee(
                employee_id="E200",
                name="Marcus Webb",
                role="standard",
                hire_date=date(2026, 11, 2),
                equipment=(),
            ),
        }
    )


def test_returns_the_role_and_tenure_of_a_known_employee(repository):
    info = repository.get_employee_info("E100", as_of=TODAY)

    assert info["employee_id"] == "E100"
    assert info["name"] == "Priya Raman"
    assert info["role"] == "standard"
    assert info["tenure_years"] == 7


def test_returns_the_equipment_on_file(repository):
    info = repository.get_employee_info("E100", as_of=TODAY)

    assert info["equipment"] == [
        {"name": "laptop", "issued_on": "2022-03-01"},
        {"name": "monitor", "issued_on": "2022-03-01"},
    ]


def test_employee_with_no_equipment_returns_an_empty_list(repository):
    info = repository.get_employee_info("E200", as_of=TODAY)

    assert info["equipment"] == []
    assert info["tenure_years"] == 0


def test_unknown_employee_id_raises(repository):
    with pytest.raises(EmployeeNotFoundError):
        repository.get_employee_info("E999", as_of=TODAY)


def test_the_result_is_json_serialisable(repository):
    """An MCP tool must return something that converts to JSON."""
    info = repository.get_employee_info("E100", as_of=TODAY)

    assert json.loads(json.dumps(info)) == info


def test_from_json_file_parses_dates(tmp_path):
    path = tmp_path / "employees.json"
    path.write_text(
        json.dumps(
            [
                {
                    "employee_id": "E300",
                    "name": "Sofia Brandt",
                    "role": "engineer",
                    "hire_date": "2015-01-12",
                    "equipment": [{"name": "laptop", "issued_on": "2025-08-20"}],
                }
            ]
        ),
        encoding="utf-8",
    )

    info = EmployeeRepository.from_json_file(path).get_employee_info("E300", as_of=TODAY)

    assert info["role"] == "engineer"
    assert info["tenure_years"] == 11
    assert info["equipment"] == [{"name": "laptop", "issued_on": "2025-08-20"}]


def test_the_committed_data_file_loads():
    """A typo in data/employees.json should fail CI, not a live demo."""
    repository = EmployeeRepository.from_json_file(DATA_FILE)

    info = repository.get_employee_info("E001", as_of=TODAY)

    assert info["role"] == "standard"
    assert info["tenure_years"] == 7
