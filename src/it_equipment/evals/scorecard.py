"""What the eval runner prints around the agent's own trace, and the scorecard at the end.

For each run of each case, in the order they happen:

    Case <id>, run k of N    which case, which run, and what it is meant to show
    (the agent's trace)      printed by the agent itself, exactly as from the
                             command line
    Result                   passed or failed, the problems numbered, and
                             the model calls the run made

Then the scorecard: one row per case, a row for all runs, and every failed
run's problems again, so they need not be found among the traces.

Values line up in the trace's column and prose wraps at its width, using the
trace's own layout helpers, so the runner's output reads as one piece.
"""

from dataclasses import dataclass

from it_equipment.agent.trace import (
    LINE_WIDTH,
    VALUE_COLUMN,
    lines_under_label,
    numbered_text,
    wrapped_lines_under_label,
)
from it_equipment.evals.cases import EvalCase
from it_equipment.evals.grading import RunGrade


@dataclass(frozen=True)
class CaseRun:
    """One run of one case: which case and run it was, how it was graded, and its model calls."""

    case_id: str
    # Counted from 1 within the case.
    run_number: int
    grade: RunGrade
    model_calls: int


def print_case_heading(case: EvalCase, run_number: int, runs: int) -> None:
    """Print which case and run comes next, and what the case is meant to show."""
    print(f"Case {case.case_id}, run {run_number} of {runs}")
    print(wrapped_lines_under_label("Expected", case.summary))
    print()


def print_run_result(case_run: CaseRun) -> None:
    """Print how one run was graded, under the agent's trace."""
    outcome = "failed"
    if case_run.grade.passed():
        outcome = "passed"

    # Numbered text is wrapped to the room left after the value column.
    room = LINE_WIDTH - VALUE_COLUMN

    print()
    print("Result")
    print(lines_under_label("Outcome", outcome))
    print(lines_under_label("Problems", numbered_text(case_run.grade.problems, room)))
    print(lines_under_label("Model calls", str(case_run.model_calls)))


def print_scorecard(cases: list[EvalCase], runs: int, case_runs: list[CaseRun]) -> None:
    """Print one row per case, a row for all runs, then each failed run's problems."""
    print(
        f"Scorecard: {plural(len(cases), 'case')}, {plural(runs, 'run')} each, "
        f"{plural(len(case_runs), 'run')} in all"
    )

    rows = [["Case", "Passed", "Model calls"]]
    for case in cases:
        rows.append(scorecard_row(case.case_id, runs_of_case(case.case_id, case_runs)))
    rows.append(all_runs_row(case_runs))

    for line in table_lines(rows):
        print(line)

    print()
    print("Failed runs")
    failed = failed_runs(case_runs)
    if len(failed) == 0:
        print("  none")
    for case_run in failed:
        print(f"  {case_run.case_id}, run {case_run.run_number}")
        # Indented under the run's line, wrapped to the room that is left.
        for line in numbered_text(case_run.grade.problems, LINE_WIDTH - 4).splitlines():
            print(f"    {line}")


def scorecard_row(case_id: str, case_runs: list[CaseRun]) -> list[str]:
    """Return one case's row: how many runs passed, and each run's model calls."""
    passed = 0
    model_calls = []
    for case_run in case_runs:
        if case_run.grade.passed():
            passed = passed + 1
        model_calls.append(str(case_run.model_calls))

    return [case_id, f"{passed} of {len(case_runs)}", ", ".join(model_calls)]


def all_runs_row(case_runs: list[CaseRun]) -> list[str]:
    """Return the row for every run together: how many passed, and the model calls in all."""
    passed = 0
    model_calls = 0
    for case_run in case_runs:
        if case_run.grade.passed():
            passed = passed + 1
        model_calls = model_calls + case_run.model_calls

    return ["All runs", f"{passed} of {len(case_runs)}", plural(model_calls, "model call")]


def runs_of_case(case_id: str, case_runs: list[CaseRun]) -> list[CaseRun]:
    """Return the runs of one case, in the order they ran."""
    chosen = []
    for case_run in case_runs:
        if case_run.case_id == case_id:
            chosen.append(case_run)

    return chosen


def failed_runs(case_runs: list[CaseRun]) -> list[CaseRun]:
    """Return the runs that have a problem, in the order they ran."""
    failed = []
    for case_run in case_runs:
        if not case_run.grade.passed():
            failed.append(case_run)

    return failed


def table_lines(rows: list[list[str]]) -> list[str]:
    """Return rows as the lines of a table, indented, with two spaces between columns.

    Each column is as wide as its widest cell, so the columns line up however
    long a case id or a list of model calls is.
    """
    widths = []
    for _ in rows[0]:
        widths.append(0)
    for row in rows:
        for column in range(len(row)):
            if len(row[column]) > widths[column]:
                widths[column] = len(row[column])

    lines = []
    for row in rows:
        cells = []
        for column in range(len(row)):
            cells.append(row[column].ljust(widths[column]))
        # The last cell is padded too, which would leave spaces at the end.
        lines.append(("  " + "  ".join(cells)).rstrip())

    return lines


def plural(count: int, word: str) -> str:
    """Return a count with its word, e.g. "1 run" or "3 runs"."""
    if count == 1:
        return f"{count} {word}"

    return f"{count} {word}s"
