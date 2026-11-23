"""The data types that describe an employee and the equipment they hold.

These are plain data classes with no file or network access, so they can be
created directly in a test without any setup.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class EquipmentItem:
    """One piece of equipment currently on file for an employee."""

    name: str
    issued_on: date

    def to_dict(self) -> dict:
        """Convert to plain types that can be written as JSON."""
        return {
            "name": self.name,
            "issued_on": self.issued_on.isoformat(),
        }


@dataclass(frozen=True)
class Employee:
    """An employee record as held in the mock HR data."""

    employee_id: str
    name: str
    role: str
    hire_date: date
    equipment: list[EquipmentItem]

    def tenure_years(self, as_of: date) -> int:
        """Return the employee's whole years of service as of a given date.

        The date is passed in rather than read from the system clock. That
        keeps this a pure calculation: the same inputs always give the same
        answer, so a test can assert a fixed number instead of one that
        changes as the calendar moves on.
        """
        # Subtracting the years alone is usually one too many, because the
        # current year is only part way through. Someone hired on 2020-03-01
        # has not served six years on 2026-02-28, only five.
        years = as_of.year - self.hire_date.year

        anniversary_passed = True

        if as_of.month < self.hire_date.month:
            # Earlier month than the hire month, so the anniversary is ahead.
            anniversary_passed = False
        elif as_of.month == self.hire_date.month:
            if as_of.day < self.hire_date.day:
                # Right month, but the day has not come round yet.
                anniversary_passed = False

        if not anniversary_passed:
            years -= 1

        return years


@dataclass(frozen=True)
class EmployeeInfo:
    """What the get_employee_info tool answers with.

    This names the tool's return shape, so callers read info.role rather
    than info["role"] and a mistyped field is a visible mistake.

    It is a separate type from Employee on purpose: Employee is the record as
    stored, while this is the answer to one question about it at one point in
    time, which is why it holds tenure_years rather than hire_date.
    """

    employee_id: str
    name: str
    role: str
    tenure_years: int
    equipment: list[EquipmentItem]

    def to_dict(self) -> dict:
        """Convert to plain types, ready to be returned by an MCP tool.

        An MCP tool result has to convert to JSON, and this is the one place
        that conversion happens on the way out.
        """
        equipment = []
        for item in self.equipment:
            equipment.append(item.to_dict())

        return {
            "employee_id": self.employee_id,
            "name": self.name,
            "role": self.role,
            "tenure_years": self.tenure_years,
            "equipment": equipment,
        }
