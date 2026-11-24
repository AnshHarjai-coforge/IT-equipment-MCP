"""Unit tests for the Employee and EquipmentItem data types."""

from datetime import date

from it_equipment.models import Employee, EquipmentItem, whole_years_between


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


def test_equipment_item_to_dict_uses_a_text_date():
    item = EquipmentItem(name="laptop", issued_on=date(2022, 3, 1))

    assert item.to_dict() == {"name": "laptop", "issued_on": "2022-03-01"}


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
        "equipment": [{"name": "laptop", "issued_on": "2022-03-01"}],
    }


def test_employee_to_dict_replaces_the_hire_date_with_tenure():
    employee = make_employee(date(2019, 4, 15))

    result = employee.to_dict(as_of=date(2026, 11, 23))

    assert "hire_date" not in result
    assert result["tenure_years"] == 7
