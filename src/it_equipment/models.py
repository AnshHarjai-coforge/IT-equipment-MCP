"""The data types that describe employees, their equipment, and the policies.

These are plain data classes with no file or network access, so they can be
created directly in a test without any setup.
"""

import calendar
from dataclasses import dataclass
from datetime import date


def count_whole_years(start: date, end: date) -> int:
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


def date_after_whole_years(start: date, years: int) -> date:
    """Return the date a given number of whole years after a start date.

    This is the reverse of count_whole_years, and is used to work out the
    date an item becomes due for replacement. The two must agree: on the date
    this returns, count_whole_years(start, ...) has just reached the number
    of years added, and not a day earlier.
    """
    target_year = start.year + years

    if start.month == 2 and start.day == 29:
        if not calendar.isleap(target_year):
            # There is no 29 February in that year. count_whole_years counts
            # such a year as completed on 1 March, so the due date is 1 March
            # too. Picking 28 February instead would name a day on which the
            # item is still a year short.
            return date(target_year, 3, 1)

    return date(target_year, start.month, start.day)


@dataclass(frozen=True)
class EquipmentItem:
    """One piece of equipment currently on file for an employee."""

    name: str
    issued_on: date

    def age_years(self, as_of: date) -> int:
        """Return how many whole years the item has been held as of a given date.

        The date is passed in for the same reason as in tenure_years: the
        answer depends only on the inputs, so a test can assert a fixed number.
        """
        return count_whole_years(self.issued_on, as_of)

    def to_dict(self, as_of: date) -> dict:
        """Convert to plain types that can be written as JSON.

        The issue date is replaced by the age in whole years, which is what the
        refresh rules are written in terms of. The model reading this gets a
        number to relay, never a date it would have to subtract itself.
        """
        return {
            "name": self.name,
            "age_years": self.age_years(as_of),
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
        return count_whole_years(self.hire_date, as_of)

    def to_dict(self, as_of: date) -> dict:
        """Convert to plain types, ready to be returned by an MCP tool.

        This is the shape the get_employee_info tool answers with, and the one
        place where the conversion to JSON happens on the way out.

        No dates are returned. The hire date is replaced by tenure_years and
        each issue date by the item's age_years, both calculated here from
        as_of rather than stored, so neither can go stale.
        """
        equipment = []
        for item in self.equipment:
            # Each item needs the same date, so its age is measured on the
            # same day as the tenure beside it.
            equipment.append(item.to_dict(as_of))

        return {
            "employee_id": self.employee_id,
            "name": self.name,
            "role": self.role,
            "tenure_years": self.tenure_years(as_of),
            "equipment": equipment,
        }


@dataclass(frozen=True)
class ItemAllowance:
    """What one role may hold of one item, and how often it is replaced."""

    item: str
    max_quantity: int
    refresh_years: int

    def to_dict(self) -> dict:
        """Convert to plain types that can be written as JSON."""
        return {
            "item": self.item,
            "max_quantity": self.max_quantity,
            "refresh_years": self.refresh_years,
        }


@dataclass(frozen=True)
class RolePolicy:
    """Everything one role is eligible for.

    An item that is missing from the list is one the role is not issued at
    all, so there is no separate "not allowed" entry.
    """

    role: str
    items: list[ItemAllowance]

    def issues(self, item: str) -> bool:
        """Return whether this role is issued the item at all."""
        for allowance in self.items:
            if allowance.item == item:
                return True

        return False

    def allowance_for(self, item: str) -> ItemAllowance:
        """Return this role's allowance for the item.

        Raises KeyError if the role is not issued the item. Call issues()
        first: not being issued an item is a normal answer, and this raises
        only so that a forgotten check can never pass as an allowance of None.
        """
        for allowance in self.items:
            if allowance.item == item:
                return allowance

        raise KeyError(f"The {self.role} role is not issued a {item}")

    def to_dict(self) -> dict:
        """Convert to plain types, ready to be returned by an MCP tool.

        This is the shape the get_policy_limits tool answers with.
        """
        items = []
        for allowance in self.items:
            items.append(allowance.to_dict())

        return {
            "role": self.role,
            "items": items,
        }
