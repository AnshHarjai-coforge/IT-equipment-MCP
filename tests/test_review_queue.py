"""Unit tests for ReviewFlag and ReviewQueue, called directly as plain Python.

The flag's id and time are fixed constants rather than a fresh uuid4() and
datetime.now(), so every expected value below is a constant.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from it_equipment.review_queue import ReviewFlag, ReviewQueue

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


@pytest.fixture
def aishas_flag() -> ReviewFlag:
    """Demo request 3, a second flag so a test can tell two lines apart."""
    return ReviewFlag(
        flag_id="0c5a7e31-2b6d-4f8e-9a1c-3d4b5e6f7a80",
        employee_id="E005",
        request="Can I get a standing desk?",
        reason="No policy covers a standing desk.",
        flagged_at=FLAGGED_AT,
    )


def read_lines(path: Path) -> list[str]:
    """Return the lines of a queue file, read directly rather than through the queue."""
    return path.read_text(encoding="utf-8").splitlines()


def test_one_flag_gives_one_line(tmp_path, sofias_flag):
    queue_file = tmp_path / "review_queue.jsonl"
    queue = ReviewQueue(queue_file)

    queue.add(sofias_flag)

    lines = read_lines(queue_file)
    assert len(lines) == 1
    assert json.loads(lines[0]) == sofias_flag.to_dict()


def test_two_flags_give_two_lines_in_the_order_added(tmp_path, sofias_flag, aishas_flag):
    queue_file = tmp_path / "review_queue.jsonl"
    queue = ReviewQueue(queue_file)

    queue.add(sofias_flag)
    queue.add(aishas_flag)

    lines = read_lines(queue_file)
    assert len(lines) == 2
    assert json.loads(lines[0]) == sofias_flag.to_dict()
    assert json.loads(lines[1]) == aishas_flag.to_dict()


def test_every_line_is_valid_json(tmp_path, sofias_flag, aishas_flag):
    queue_file = tmp_path / "review_queue.jsonl"
    queue = ReviewQueue(queue_file)

    queue.add(sofias_flag)
    queue.add(aishas_flag)
    queue.add(sofias_flag)

    records = []
    for line in read_lines(queue_file):
        # json.loads raises JSONDecodeError on a line that is not valid JSON.
        records.append(json.loads(line))

    assert len(records) == 3


def test_the_folder_is_created_if_it_does_not_exist(tmp_path, sofias_flag):
    queue_file = tmp_path / "review-queue" / "review_queue.jsonl"
    queue = ReviewQueue(queue_file)

    queue.add(sofias_flag)

    assert queue_file.exists()


def test_creating_a_queue_writes_nothing(tmp_path):
    """Only adding a flag touches the disk, so building a server makes no files."""
    queue_file = tmp_path / "review-queue" / "review_queue.jsonl"

    ReviewQueue(queue_file)

    assert not queue_file.parent.exists()


def test_a_request_with_a_line_break_is_still_one_line(tmp_path):
    queue_file = tmp_path / "review_queue.jsonl"
    queue = ReviewQueue(queue_file)
    flag = ReviewFlag(
        flag_id=FLAG_ID,
        employee_id="E003",
        request="I dropped my laptop.\nThe screen is cracked.",
        reason="The damage cannot be confirmed from the records.",
        flagged_at=FLAGGED_AT,
    )

    queue.add(flag)

    lines = read_lines(queue_file)
    assert len(lines) == 1
    assert json.loads(lines[0])["request"] == "I dropped my laptop.\nThe screen is cracked."


def test_flags_already_in_the_file_are_kept(tmp_path, sofias_flag, aishas_flag):
    """A new queue on the same file, as after a server restart, appends to it."""
    queue_file = tmp_path / "review_queue.jsonl"
    ReviewQueue(queue_file).add(sofias_flag)

    ReviewQueue(queue_file).add(aishas_flag)

    lines = read_lines(queue_file)
    assert len(lines) == 2
    assert json.loads(lines[0]) == sofias_flag.to_dict()
