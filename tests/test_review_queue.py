"""Unit tests for ReviewFlag and ReviewQueue, called directly as plain Python.

The flag's id and time are fixed constants rather than a fresh uuid4() and
datetime.now(), so every expected value below is a constant.
"""

import json
from datetime import datetime, timezone

import pytest

from it_equipment.review_queue import ReviewFlag

FLAG_ID = "9b1d6c2e-4f7a-4c1e-8a3b-2d5e6f708192"

# A fixed moment, with microseconds, so the tests show they are dropped.
FLAGGED_AT = datetime(2026, 11, 23, 14, 3, 12, 482913, tzinfo=timezone.utc)


@pytest.fixture
def sofias_flag() -> ReviewFlag:
    """Demo request 4: damage the records cannot confirm."""
    return ReviewFlag(
        flag_id=FLAG_ID,
        employee_id="E003",
        request="I dropped my laptop and cracked the screen. I need a replacement.",
        reason="The damage cannot be confirmed from the records.",
        flagged_at=FLAGGED_AT,
    )


def test_a_flag_converts_to_json_ready_types(sofias_flag):
    assert sofias_flag.to_dict() == {
        "flag_id": FLAG_ID,
        "employee_id": "E003",
        "request": "I dropped my laptop and cracked the screen. I need a replacement.",
        "reason": "The damage cannot be confirmed from the records.",
        "flagged_at": "2026-11-23T14:03:12+00:00",
    }


def test_the_flag_is_json_serialisable(sofias_flag):
    flag = sofias_flag.to_dict()

    # json.dumps raises TypeError if any value cannot be converted.
    as_json = json.dumps(flag)

    assert json.loads(as_json) == flag
