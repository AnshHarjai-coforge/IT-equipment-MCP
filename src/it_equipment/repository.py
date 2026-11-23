"""Employee lookups: the logic behind the get_employee_info MCP tool.

This module is plain Python with no MCP imports. The MCP server will wrap
get_employee_info in a thin tool function, which keeps this logic directly
callable from a unit test.
"""

import json
from datetime import date
from pathlib import Path

from it_equipment.models import Employee, EquipmentItem


class EmployeeNotFoundError(KeyError):
    """Raised when no employee exists for the requested employee id."""


class EmployeeRepository:
    """Read-only access to the employee records, held in memory.

    The records are handed to the constructor rather than loaded by it. That
    separates reading a file from looking data up, so a test can build a
    repository from a literal, and there is no module-level state to reset
    between tests.
    """

    def __init__(self, employees: dict[str, Employee]) -> None:
        self._employees = employees  # employee_id -> Employee object

    def get_employee(self, employee_id: str) -> Employee:
        """Return the employee record with this id.

        This is a lookup and nothing more. Call to_dict(as_of) on the result
        at the point where it has to become JSON, such as in an MCP tool.

        Raises EmployeeNotFoundError if the id is unknown. Raising rather than
        returning None means a caller cannot mistake a missing employee for an
        employee who simply holds no equipment.
        """
        if employee_id not in self._employees:
            raise EmployeeNotFoundError(f"No employee with id '{employee_id}'")

        return self._employees[employee_id]


def load_employees_from_json(path: str | Path) -> EmployeeRepository:
    """Read a JSON file of employee records and return a repository of them.

    This is the only place in the package that reads a file.
    """
    text = Path(path).read_text(encoding="utf-8")
    records = json.loads(text)

    # Index the records by employee id, so a lookup does not scan the list.
    employees = {}
    for record in records:
        employee = build_employee(record)
        employees[employee.employee_id] = employee

    return EmployeeRepository(employees)


def build_employee(record: dict) -> Employee:
    """Turn one record from the JSON file into an Employee.

    JSON has no date type, so the hire and issue dates arrive as text such as
    "2022-03-01" and are converted into real date objects here.
    """
    equipment = []
    for item in record["equipment"]:
        equipment.append(
            EquipmentItem(
                name=item["name"],
                issued_on=date.fromisoformat(item["issued_on"]),
            )
        )

    return Employee(
        employee_id=record["employee_id"],
        name=record["name"],
        role=record["role"],
        hire_date=date.fromisoformat(record["hire_date"]),
        equipment=equipment,
    )
