"""The data types that describe an employee and the equipment they hold.

These are plain data classes with no file or network access, so they can be
created directly in a test without any setup.
"""

from dataclasses import dataclass
from datetime import date


def whole_years_between(start: date, end: date) -> int:
    """Return how many full years have passed from one date to a later one.

    Both tenure and equipment age are counted this way. Keeping the anniversary
    logic in one function means the two can never disagree about when a year
    has been completed.
    """
    # Subtracting the years alone is usually one too many, because the
    # current year is only part way through. Someone hired on 2020-03-01
    # has not served six years on 2026-02-28, only five.
    years = end.year - start.year

    anniversary_passed = True

    if end.month < start.month:
        # Earlier month than the start month, so the anniversary is ahead.
        anniversary_passed = False
    elif end.month == start.month:
        # A start date of 29 February also lands here. In a year without one,
        # 28 February is still short of the 29th, so the year is completed on
        # 1 March instead.
        if end.day < start.day:
            # Right month, but the day has not come round yet.
            anniversary_passed = False

    if not anniversary_passed:
        years -= 1

    return years


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
        return whole_years_between(self.hire_date, as_of)

    def to_dict(self, as_of: date) -> dict:
        """Convert to plain types, ready to be returned by an MCP tool.

        This is the shape the get_employee_info tool answers with, and the one
        place where the conversion to JSON happens on the way out. Dates become
        text in ISO format (YYYY-MM-DD), because JSON has no date type.

        The hire date is replaced by tenure_years, which is what the policy
        rules are written in terms of. It is calculated here from as_of rather
        than stored, so it cannot go stale.
        """
        equipment = []
        for item in self.equipment:
            equipment.append(item.to_dict())

        return {
            "employee_id": self.employee_id,
            "name": self.name,
            "role": self.role,
            "tenure_years": self.tenure_years(as_of),
            "equipment": equipment,
        }
