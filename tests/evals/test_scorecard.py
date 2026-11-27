"""Unit tests for what the eval runner prints: each run's heading and result, and the scorecard.

Each run is a literal CaseRun with a literal grade, so nothing is run or paid
for. Printed output is read back with pytest's capsys.
"""

from it_equipment.agent.request import EquipmentRequest
from it_equipment.evals.cases import EvalCase, ExpectedOutcome
from it_equipment.evals.grading import RunGrade
from it_equipment.evals.scorecard import (
    CaseRun,
    numbered_text,
    plural,
    print_case_heading,
    print_run_result,
    print_scorecard,
    table_lines,
)

PASSED = RunGrade(problems=[])
NO_FLAG = RunGrade(
    problems=[
        "Decision: expected escalated; the draft says denied.",
        "Flags: expected 1; recorded 0.",
    ]
)


def case(case_id: str, summary: str = "Approved: the replacement is due.") -> EvalCase:
    return EvalCase(
        case_id=case_id,
        summary=summary,
        request=EquipmentRequest(employee_id="E001", text="A request."),
        expected=ExpectedOutcome(
            decision="approved", item="laptop", answered="replacement", flagged=False
        ),
        verdicts=None,
        required_calls=[],
        forbidden_calls=[],
    )


def test_the_heading_names_the_case_and_the_run_and_ends_with_a_blank_line(capsys):
    print_case_heading(case("1-approved-replacement"), 2, 3)

    assert capsys.readouterr().out == (
        "Case 1-approved-replacement, run 2 of 3\n"
        "  Expected:       Approved: the replacement is due.\n"
        "\n"
    )


def test_a_long_summary_wraps_under_its_label(capsys):
    """16 of these words fit in the 82 columns after the label; the other 14 go below."""
    summary = "word " * 30

    print_case_heading(case("8-escalated-injection", summary), 1, 1)

    lines = capsys.readouterr().out.splitlines()
    assert lines[2] == " " * 18 + "word" + " word" * 13


def test_a_passed_run_prints_none_for_problems(capsys):
    print_run_result(CaseRun("5-not-processed-unknown-id", 1, PASSED, 2))

    assert capsys.readouterr().out == (
        "\nResult\n  Outcome:        passed\n  Problems:       none\n  Model calls:    2\n"
    )


def test_a_failed_run_prints_its_problems_numbered(capsys):
    print_run_result(CaseRun("4-escalated-damage-claim", 1, NO_FLAG, 3))

    printed = capsys.readouterr().out
    assert "  Outcome:        failed\n" in printed
    assert (
        "  Problems:       1. Decision: expected escalated; the draft says denied.\n"
        "                  2. Flags: expected 1; recorded 0.\n"
    ) in printed


def test_a_long_numbered_sentence_carries_on_under_its_first_word():
    sentence = "Flag id: the draft gives a flag id which this run did not receive."

    text = numbered_text([sentence], 40)

    assert text == "1. Flag id: the draft gives a flag id\n   which this run did not receive."


def test_no_sentences_are_written_as_none():
    assert numbered_text([], 80) == "none"


def test_table_columns_line_up_with_two_spaces_between():
    lines = table_lines([["Case", "Passed"], ["1-approved-replacement", "3 of 3"]])

    assert lines == [
        "  Case                    Passed",
        "  1-approved-replacement  3 of 3",
    ]


def test_one_is_singular_and_any_other_count_plural():
    assert [plural(1, "run"), plural(3, "run"), plural(0, "run")] == ["1 run", "3 runs", "0 runs"]


def test_the_scorecard_has_a_row_per_case_and_a_row_for_all_runs(capsys):
    cases = [case("1-approved-replacement"), case("4-escalated-damage-claim")]
    runs = [
        CaseRun("1-approved-replacement", 1, PASSED, 3),
        CaseRun("1-approved-replacement", 2, PASSED, 2),
        CaseRun("4-escalated-damage-claim", 1, PASSED, 4),
        CaseRun("4-escalated-damage-claim", 2, NO_FLAG, 3),
    ]

    print_scorecard(cases, 2, runs)

    assert capsys.readouterr().out.startswith(
        "Scorecard: 2 cases, 2 runs each, 4 runs in all\n"
        "  Case                      Passed  Model calls\n"
        "  1-approved-replacement    2 of 2  3, 2\n"
        "  4-escalated-damage-claim  1 of 2  4, 3\n"
        "  All runs                  3 of 4  12 model calls\n"
    )


def test_the_scorecard_ends_with_each_failed_runs_problems(capsys):
    runs = [
        CaseRun("4-escalated-damage-claim", 1, PASSED, 4),
        CaseRun("4-escalated-damage-claim", 2, NO_FLAG, 3),
    ]

    print_scorecard([case("4-escalated-damage-claim")], 2, runs)

    assert capsys.readouterr().out.endswith(
        "\n"
        "Failed runs\n"
        "  4-escalated-damage-claim, run 2\n"
        "    1. Decision: expected escalated; the draft says denied.\n"
        "    2. Flags: expected 1; recorded 0.\n"
    )


def test_a_scorecard_with_no_failures_says_none(capsys):
    print_scorecard(
        [case("1-approved-replacement")], 1, [CaseRun("1-approved-replacement", 1, PASSED, 3)]
    )

    assert capsys.readouterr().out.endswith("\nFailed runs\n  none\n")
