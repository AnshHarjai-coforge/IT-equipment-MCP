"""Employee and policy lookups: the logic behind the MCP tools.

This module is plain Python with no MCP imports. The MCP server wraps these
lookups in thin tool functions, which keeps the logic directly callable from a
unit test.
"""

import json
from datetime import date
from pathlib import Path

from it_equipment.models import Employee, EquipmentItem, ItemAllowance, RolePolicy


class EmployeeNotFoundError(KeyError):
    """Raised when no employee exists for the requested employee id."""


class RoleNotFoundError(KeyError):
    """Raised when no policy exists for the requested role."""


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


class PolicyRepository:
    """Read-only access to the policy for each role, held in memory.

    Built the same way as EmployeeRepository: the records are handed in, so a
    test can build one from a literal without a file.
    """

    def __init__(self, policies: dict[str, RolePolicy]) -> None:
        self._policies = policies  # role -> RolePolicy object

    def get_policy(self, role: str) -> RolePolicy:
        """Return the policy for this role.

        The role must match exactly. Guessing at a near miss here would mean a
        typo could quietly pick up some other role's limits.

        Raises RoleNotFoundError if no policy exists for the role. The message
        lists the roles that do have one, so whoever reads it can see what was
        expected rather than only what was wrong.
        """
        if role not in self._policies:
            known_roles = ", ".join(self._policies.keys())
            raise RoleNotFoundError(f"No policy for role '{role}'. Known roles: {known_roles}")

        return self._policies[role]

    def catalogue(self) -> list[str]:
        """Return every item that any role's policy mentions, each name once.

        The catalogue is worked out from the policies rather than kept as a
        separate list, so an item cannot be added to one and forgotten in the
        other.
        """
        items = []
        for policy in self._policies.values():
            for allowance in policy.items:
                # Several roles list the same item, and it should appear once.
                if allowance.item not in items:
                    items.append(allowance.item)

        return items


def load_employees_from_json(path: str | Path) -> EmployeeRepository:
    """Read a JSON file of employee records and return a repository of them.

    This and load_policies_from_json are the only places in the package that
    read a data file.
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


def load_policies_from_json(path: str | Path) -> PolicyRepository:
    """Read a JSON file of role policies and return a repository of them.

    This and load_employees_from_json are the only places in the package that
    read a data file.
    """
    text = Path(path).read_text(encoding="utf-8")
    records = json.loads(text)

    # Index the policies by role, so a lookup does not scan the list.
    policies = {}
    for record in records:
        policy = build_role_policy(record)
        policies[policy.role] = policy

    return PolicyRepository(policies)


def build_role_policy(record: dict) -> RolePolicy:
    """Turn one record from the JSON file into a RolePolicy."""
    items = []
    for item in record["items"]:
        items.append(
            ItemAllowance(
                item=item["item"],
                max_quantity=item["max_quantity"],
                refresh_years=item["refresh_years"],
            )
        )

    return RolePolicy(role=record["role"], items=items)
