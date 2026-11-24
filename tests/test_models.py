"""Unit tests for the data types: employees, their equipment, and the policies."""

from datetime import date, timedelta

from it_equipment.models import (
    Employee,
    EquipmentItem,
    ItemAllowance,
    RolePolicy,
    add_whole_years,
    whole_years_between,
)


def make_employee(hire_date: date) -> Employee:
    """Build an employee whose only interesting property is the hire date."""
    return Employee(
        employee_id="E100",
        name="Test Employee",
        role="standard",
        hire_date=hire_date,
        equipment=[],
    )


def test_whole_years_between_counts_only_completed_years():
    assert whole_years_between(date(2022, 3, 1), date(2026, 2, 28)) == 3
    assert whole_years_between(date(2022, 3, 1), date(2026, 3, 1)) == 4


def test_whole_years_between_is_zero_within_the_first_year():
    assert whole_years_between(date(2026, 11, 2), date(2026, 11, 23)) == 0


def test_a_29_february_start_completes_its_year_on_1_march_in_a_common_year():
    # 2025 has no 29 February, so the first year ends a day later than 28 February.
    assert whole_years_between(date(2024, 2, 29), date(2025, 2, 28)) == 0
    assert whole_years_between(date(2024, 2, 29), date(2025, 3, 1)) == 1


def test_a_29_february_start_completes_its_year_on_29_february_in_a_leap_year():
    assert whole_years_between(date(2024, 2, 29), date(2028, 2, 28)) == 3
    assert whole_years_between(date(2024, 2, 29), date(2028, 2, 29)) == 4


def test_add_whole_years_keeps_the_month_and_day():
    assert add_whole_years(date(2025, 8, 20), 3) == date(2028, 8, 20)


def test_add_whole_years_from_29_february_lands_on_1_march_in_a_common_year():
    assert add_whole_years(date(2024, 2, 29), 1) == date(2025, 3, 1)


def test_add_whole_years_from_29_february_stays_on_29_february_in_a_leap_year():
    assert add_whole_years(date(2024, 2, 29), 4) == date(2028, 2, 29)


def test_add_whole_years_agrees_with_whole_years_between():
    """The due date is the first day on which the item is old enough.

    For each start date, the years are complete on the date add_whole_years
    returns and still one short the day before. The 29 February start covers
    both a common year (2025) and a leap year (2028).
    """
    starts = [date(2022, 3, 1), date(2025, 8, 20), date(2024, 2, 29), date(2023, 12, 31)]

    for start in starts:
        for years in [1, 2, 3, 4]:
            due = add_whole_years(start, years)
            day_before = due - timedelta(days=1)

            assert whole_years_between(start, due) == years
            assert whole_years_between(start, day_before) == years - 1


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


def test_tenure_years_for_a_29_february_hire():
    # E006 Tomas in the mock data was hired on this date.
    employee = make_employee(date(2024, 2, 29))

    assert employee.tenure_years(as_of=date(2025, 2, 28)) == 0
    assert employee.tenure_years(as_of=date(2025, 3, 1)) == 1


def test_equipment_item_holds_a_real_date():
    item = EquipmentItem(name="laptop", issued_on=date(2022, 3, 1))

    assert item.name == "laptop"
    assert item.issued_on.year == 2022


def test_age_years_counts_whole_years_since_issue():
    item = EquipmentItem(name="laptop", issued_on=date(2022, 3, 1))

    assert item.age_years(as_of=date(2026, 2, 28)) == 3
    assert item.age_years(as_of=date(2026, 3, 1)) == 4


def test_age_years_is_zero_for_an_item_issued_this_year():
    item = EquipmentItem(name="laptop", issued_on=date(2026, 11, 2))

    assert item.age_years(as_of=date(2026, 11, 23)) == 0


def test_age_years_for_an_item_issued_on_29_february():
    item = EquipmentItem(name="laptop", issued_on=date(2024, 2, 29))

    assert item.age_years(as_of=date(2025, 2, 28)) == 0
    assert item.age_years(as_of=date(2025, 3, 1)) == 1


def test_equipment_item_to_dict_reports_age_instead_of_the_issue_date():
    item = EquipmentItem(name="laptop", issued_on=date(2022, 3, 1))

    assert item.to_dict(as_of=date(2026, 11, 23)) == {"name": "laptop", "age_years": 4}


def test_employee_to_dict_is_the_shape_the_tool_returns():
    employee = Employee(
        employee_id="E100",
        name="Priya Raman",
        role="standard",
        hire_date=date(2019, 4, 15),
        equipment=[EquipmentItem(name="laptop", issued_on=date(2022, 3, 1))],
    )

    assert employee.to_dict(as_of=date(2026, 11, 23)) == {
        "employee_id": "E100",
        "name": "Priya Raman",
        "role": "standard",
        "tenure_years": 7,
        "equipment": [{"name": "laptop", "age_years": 4}],
    }


def test_employee_to_dict_replaces_the_hire_date_with_tenure():
    employee = make_employee(date(2019, 4, 15))

    result = employee.to_dict(as_of=date(2026, 11, 23))

    assert "hire_date" not in result
    assert result["tenure_years"] == 7


def test_item_allowance_to_dict():
    allowance = ItemAllowance(item="monitor", max_quantity=2, refresh_years=4)

    assert allowance.to_dict() == {"item": "monitor", "max_quantity": 2, "refresh_years": 4}


def test_role_policy_to_dict_is_the_shape_the_tool_returns():
    policy = RolePolicy(
        role="standard",
        items=[
            ItemAllowance(item="laptop", max_quantity=1, refresh_years=4),
            ItemAllowance(item="monitor", max_quantity=1, refresh_years=3),
        ],
    )

    assert policy.to_dict() == {
        "role": "standard",
        "items": [
            {"item": "laptop", "max_quantity": 1, "refresh_years": 4},
            {"item": "monitor", "max_quantity": 1, "refresh_years": 3},
        ],
    }
