"""Unit tests for the eligibility check, called directly as plain Python.

Every input is built from a literal and the date is fixed, so each expected
verdict and due date is a constant.
"""

import json
from datetime import date

from it_equipment.eligibility import (
    APPROVED,
    DENIED,
    EligibilityDecision,
    Verdict,
)

# A fixed date, so every expected age and due date below is a constant.
TODAY = date(2026, 11, 23)


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
