"""Unit tests for the Employee and EquipmentItem data types."""

from datetime import date

from it_equipment.models import Employee, EquipmentItem


def make_employee(hire_date: date) -> Employee:
    """Build an employee whose only interesting property is the hire date."""
    return Employee(
        employee_id="E100",
        name="Test Employee",
        role="standard",
        hire_date=hire_date,
        equipment=[],
    )


def test_tenure_years_counts_whole_years_after_the_anniversary():
    employee = make_employee(date(2020, 3, 1))

    assert employee.tenure_years(as_of=date(2026, 6, 15)) == 6


def test_tenure_years_excludes_the_year_still_in_progress():
    # The anniversary (1 March) has not arrived yet in February 2026.
    employee = make_employee(date(2020, 3, 1))

    assert employee.tenure_years(as_of=date(2026, 2, 28)) == 5


def test_tenure_years_counts_the_anniversary_day_itself():
    employee = make_employee(date(2020, 3, 1))

    assert employee.tenure_years(as_of=date(2026, 3, 1)) == 6


def test_tenure_years_is_zero_for_a_new_hire():
    employee = make_employee(date(2026, 11, 2))

    assert employee.tenure_years(as_of=date(2026, 11, 23)) == 0


def test_equipment_item_holds_a_real_date():
    item = EquipmentItem(name="laptop", issued_on=date(2022, 3, 1))

    assert item.name == "laptop"
    assert item.issued_on.year == 2022
