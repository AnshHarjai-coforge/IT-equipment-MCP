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
        self._employees = employees

    @classmethod
    def from_json_file(cls, path: str | Path) -> "EmployeeRepository":
        """Build a repository from a JSON file of employee records."""
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        employees = {record["employee_id"]: _employee_from_record(record) for record in records}
        return cls(employees)

    def get_employee_info(self, employee_id: str, as_of: date) -> dict:
        """Return the role, tenure and equipment on file for one employee.

        The return value is a dictionary of plain strings and numbers, because
        an MCP tool has to return something that converts to JSON. Dates are
        returned in ISO format (YYYY-MM-DD) for the same reason.

        Raises EmployeeNotFoundError if the id is unknown. Raising rather than
        returning None means a caller cannot mistake a missing employee for an
        employee who simply holds no equipment.
        """
        employee = self._employees.get(employee_id)
        if employee is None:
            raise EmployeeNotFoundError(f"No employee with id {employee_id!r}")

        return {
            "employee_id": employee.employee_id,
            "name": employee.name,
            "role": employee.role,
            "tenure_years": employee.tenure_years(as_of),
            "equipment": [
                {"name": item.name, "issued_on": item.issued_on.isoformat()}
                for item in employee.equipment
            ],
        }


def _employee_from_record(record: dict) -> Employee:
    """Convert one JSON record into an Employee, parsing its date strings."""
    return Employee(
        employee_id=record["employee_id"],
        name=record["name"],
        role=record["role"],
        hire_date=date.fromisoformat(record["hire_date"]),
        equipment=tuple(
            EquipmentItem(
                name=item["name"],
                issued_on=date.fromisoformat(item["issued_on"]),
            )
            for item in record["equipment"]
        ),
    )
