"""Unit tests for the eligibility check, called directly as plain Python.

Every input is built from a literal and the date is fixed, so each expected
verdict and due date is a constant.
"""

import json
from datetime import date

from it_equipment.eligibility import (
    APPROVED,
    DENIED,
    NEEDS_REVIEW,
    EligibilityDecision,
    Verdict,
    decide_eligibility,
)
from it_equipment.models import Employee, EquipmentItem, ItemAllowance, RolePolicy

# A fixed date, so every expected age and due date below is a constant.
TODAY = date(2026, 11, 23)

# The agreed policies for two roles, written out so these tests do not read a file.
STANDARD = RolePolicy(
    role="standard",
    items=[
        ItemAllowance(item="laptop", max_quantity=1, refresh_years=4),
        ItemAllowance(item="monitor", max_quantity=1, refresh_years=3),
    ],
)
ENGINEER = RolePolicy(
    role="engineer",
    items=[
        ItemAllowance(item="laptop", max_quantity=1, refresh_years=3),
        ItemAllowance(item="monitor", max_quantity=2, refresh_years=4),
        ItemAllowance(item="docking station", max_quantity=1, refresh_years=4),
    ],
)
CATALOGUE = ["laptop", "monitor", "docking station"]


def make_employee(role: str, equipment: list[EquipmentItem]) -> Employee:
    """Build an employee whose only interesting properties are role and equipment."""
    return Employee(
        employee_id="E100",
        name="Test Employee",
        role=role,
        hire_date=date(2020, 1, 1),
        equipment=equipment,
    )


def test_verdict_to_dict_writes_the_due_date_as_text():
    verdict = Verdict(verdict=DENIED, reason="Not yet.", next_eligible_on=date(2028, 8, 20))

    assert verdict.to_dict() == {
        "verdict": "denied",
        "reason": "Not yet.",
        "next_eligible_on": "2028-08-20",
    }


def test_verdict_to_dict_without_a_due_date_gives_null():
    verdict = Verdict(verdict=APPROVED, reason="Fine.", next_eligible_on=None)

    assert verdict.to_dict()["next_eligible_on"] is None


def test_decision_to_dict_converts_each_verdict():
    decision = EligibilityDecision(
        employee_id="E003",
        role="engineer",
        item="laptop",
        held=1,
        max_quantity=1,
        refresh_years=3,
        additional=Verdict(verdict=DENIED, reason="Holds one.", next_eligible_on=None),
        replacement=Verdict(verdict=DENIED, reason="Too new.", next_eligible_on=date(2028, 8, 20)),
    )

    result = decision.to_dict()

    assert result == {
        "employee_id": "E003",
        "role": "engineer",
        "item": "laptop",
        "held": 1,
        "max_quantity": 1,
        "refresh_years": 3,
        "additional": {"verdict": "denied", "reason": "Holds one.", "next_eligible_on": None},
        "replacement": {
            "verdict": "denied",
            "reason": "Too new.",
            "next_eligible_on": "2028-08-20",
        },
    }
    # json.dumps raises TypeError if a date had been left unconverted.
    assert json.loads(json.dumps(result)) == result


def test_sofia_laptop_gives_the_example_result_from_the_plan():
    """E003 Sofia from the mock data: an engineer whose laptop is one year old."""
    sofia = Employee(
        employee_id="E003",
        name="Sofia Brandt",
        role="engineer",
        hire_date=date(2015, 1, 12),
        equipment=[
            EquipmentItem(name="laptop", issued_on=date(2025, 8, 20)),
            EquipmentItem(name="monitor", issued_on=date(2023, 2, 14)),
            EquipmentItem(name="monitor", issued_on=date(2023, 2, 14)),
        ],
    )

    result = decide_eligibility(sofia, ENGINEER, CATALOGUE, "laptop", TODAY).to_dict()

    assert result == {
        "employee_id": "E003",
        "role": "engineer",
        "item": "laptop",
        "held": 1,
        "max_quantity": 1,
        "refresh_years": 3,
        "additional": {
            "verdict": "denied",
            "reason": (
                "Employees in the engineer role may hold 1 laptop and E003 holds 1. "
                "Another laptop is not issued while 1 laptop is held, "
                "so there is no date on which this changes."
            ),
            "next_eligible_on": None,
        },
        "replacement": {
            "verdict": "denied",
            "reason": (
                "E003's laptop is 1 year old; laptops in the engineer role "
                "are replaced after 3 years."
            ),
            "next_eligible_on": "2028-08-20",
        },
    }


# Rule 1: no role's policy mentions the item.


def test_rule_1_an_item_no_policy_covers_needs_review_both_ways():
    employee = make_employee("engineer", [])

    decision = decide_eligibility(employee, ENGINEER, CATALOGUE, "standing desk", TODAY)

    assert decision.additional.verdict == NEEDS_REVIEW
    assert decision.replacement.verdict == NEEDS_REVIEW
    assert decision.max_quantity is None
    assert decision.refresh_years is None


def test_rule_1_the_reason_lists_the_covered_items():
    """So the agent can retry if it used the wrong word for a covered item."""
    employee = make_employee("engineer", [])

    decision = decide_eligibility(employee, ENGINEER, CATALOGUE, "standing desk", TODAY)

    assert "standing desk" in decision.additional.reason
    assert "laptop, monitor, docking station" in decision.additional.reason


def test_rule_1_applies_before_rule_2():
    """A standard employee is not issued a standing desk either, but nobody is.

    The catalogue is checked first, so the answer is a review rather than a
    denial that would wrongly suggest another role could have one.
    """
    employee = make_employee("standard", [])

    decision = decide_eligibility(employee, STANDARD, CATALOGUE, "standing desk", TODAY)

    assert decision.additional.verdict == NEEDS_REVIEW


# Rule 2: the role isn't issued the item.


def test_rule_2_an_item_the_role_is_not_issued_is_denied_both_ways():
    employee = make_employee("standard", [])

    decision = decide_eligibility(employee, STANDARD, CATALOGUE, "docking station", TODAY)

    assert decision.additional.verdict == DENIED
    assert decision.replacement.verdict == DENIED
    assert decision.additional.next_eligible_on is None
    assert decision.replacement.next_eligible_on is None
    assert decision.additional.reason == (
        "Employees in the standard role are not issued a docking station."
    )


# Rule 3: the records show more than the role may hold.


def test_rule_3_holding_over_the_limit_needs_review_both_ways():
    two_monitors = [
        EquipmentItem(name="monitor", issued_on=date(2020, 1, 1)),
        EquipmentItem(name="monitor", issued_on=date(2020, 1, 1)),
    ]
    employee = make_employee("standard", two_monitors)

    decision = decide_eligibility(employee, STANDARD, CATALOGUE, "monitor", TODAY)

    # Without rule 3, the replacement would be approved: the monitors are six
    # years old and standard monitors are replaced after three.
    assert decision.additional.verdict == NEEDS_REVIEW
    assert decision.replacement.verdict == NEEDS_REVIEW
    assert decision.held == 2
    assert "disagree" in decision.additional.reason


# Rule 4: an additional item.


def test_rule_4_additional_is_approved_below_the_limit():
    one_monitor = [EquipmentItem(name="monitor", issued_on=date(2025, 1, 1))]
    employee = make_employee("engineer", one_monitor)

    decision = decide_eligibility(employee, ENGINEER, CATALOGUE, "monitor", TODAY)

    assert decision.additional.verdict == APPROVED
    assert decision.additional.next_eligible_on is None


def test_rule_4_additional_is_denied_at_the_limit_and_says_there_is_no_date():
    one_monitor = [EquipmentItem(name="monitor", issued_on=date(2022, 3, 1))]
    employee = make_employee("standard", one_monitor)

    decision = decide_eligibility(employee, STANDARD, CATALOGUE, "monitor", TODAY)

    assert decision.additional.verdict == DENIED
    assert decision.additional.next_eligible_on is None
    assert "no date" in decision.additional.reason


def test_rule_4_the_denial_counts_more_than_one_held_item_correctly():
    two_monitors = [
        EquipmentItem(name="monitor", issued_on=date(2025, 1, 1)),
        EquipmentItem(name="monitor", issued_on=date(2025, 1, 1)),
    ]
    employee = make_employee("engineer", two_monitors)

    decision = decide_eligibility(employee, ENGINEER, CATALOGUE, "monitor", TODAY)

    assert decision.additional.verdict == DENIED
    assert "may hold 2 monitors and E100 holds 2" in decision.additional.reason
    assert "while 2 monitors are held" in decision.additional.reason


# Rule 5: a replacement.


def test_rule_5_replacement_is_denied_when_none_is_held():
    """E004 Marcus's case: a new starter with nothing to hand back."""
    employee = make_employee("standard", [])

    decision = decide_eligibility(employee, STANDARD, CATALOGUE, "laptop", TODAY)

    assert decision.replacement.verdict == DENIED
    assert decision.replacement.next_eligible_on is None
    assert "nothing to replace" in decision.replacement.reason
    # The same new starter may still have one as an additional item.
    assert decision.additional.verdict == APPROVED
    assert decision.held == 0


def test_rule_5_replacement_is_approved_once_the_refresh_age_is_reached():
    """E001 Priya's case: a standard laptop issued 2022-03-01, four years old."""
    laptop = [EquipmentItem(name="laptop", issued_on=date(2022, 3, 1))]
    employee = make_employee("standard", laptop)

    decision = decide_eligibility(employee, STANDARD, CATALOGUE, "laptop", TODAY)

    assert decision.replacement.verdict == APPROVED
    assert decision.replacement.next_eligible_on is None
    assert decision.replacement.reason == (
        "E100's laptop is 4 years old; laptops in the standard role are replaced after 4 years."
    )


def test_rule_5_replacement_is_denied_before_the_refresh_age_with_the_due_date():
    laptop = [EquipmentItem(name="laptop", issued_on=date(2023, 3, 1))]
    employee = make_employee("standard", laptop)

    decision = decide_eligibility(employee, STANDARD, CATALOGUE, "laptop", TODAY)

    assert decision.replacement.verdict == DENIED
    assert decision.replacement.next_eligible_on == date(2027, 3, 1)


def test_rule_5_replacement_is_approved_on_the_due_date_itself():
    laptop = [EquipmentItem(name="laptop", issued_on=date(2022, 11, 23))]
    employee = make_employee("standard", laptop)

    decision = decide_eligibility(employee, STANDARD, CATALOGUE, "laptop", TODAY)

    assert decision.replacement.verdict == APPROVED


def test_rule_5_the_oldest_item_is_the_one_replaced():
    """The newer monitor is listed first, so the oldest has to be searched for."""
    two_monitors = [
        EquipmentItem(name="monitor", issued_on=date(2025, 6, 1)),
        EquipmentItem(name="monitor", issued_on=date(2021, 6, 1)),
    ]
    employee = make_employee("engineer", two_monitors)

    decision = decide_eligibility(employee, ENGINEER, CATALOGUE, "monitor", TODAY)

    # The 2021 monitor is five years old; engineers' monitors are replaced after four.
    assert decision.replacement.verdict == APPROVED
    assert "E100's oldest monitor is 5 years old" in decision.replacement.reason


def test_rule_5_an_item_issued_on_29_february_is_due_on_1_march_in_a_common_year():
    """2027 has no 29 February, so the third year is completed on 1 March."""
    laptop = [EquipmentItem(name="laptop", issued_on=date(2024, 2, 29))]
    employee = make_employee("engineer", laptop)

    decision = decide_eligibility(employee, ENGINEER, CATALOGUE, "laptop", TODAY)

    assert decision.replacement.verdict == DENIED
    assert decision.replacement.next_eligible_on == date(2027, 3, 1)

    # And on that date the check agrees that it is due.
    on_the_day = decide_eligibility(employee, ENGINEER, CATALOGUE, "laptop", date(2027, 3, 1))
    assert on_the_day.replacement.verdict == APPROVED


def test_other_items_on_file_are_not_counted():
    """Only monitors count towards a monitor request."""
    equipment = [
        EquipmentItem(name="laptop", issued_on=date(2025, 1, 1)),
        EquipmentItem(name="docking station", issued_on=date(2025, 1, 1)),
    ]
    employee = make_employee("engineer", equipment)

    decision = decide_eligibility(employee, ENGINEER, CATALOGUE, "monitor", TODAY)

    assert decision.held == 0
    assert decision.additional.verdict == APPROVED
