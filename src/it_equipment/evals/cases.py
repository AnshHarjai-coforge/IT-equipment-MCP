"""The eval cases: the demo requests, each with the outcome and the tool calls a correct run has.

Each case is one of the demo requests in plan.md section 3, written down with
what a correct run looks like:

    expected          the draft's decision, item and answered, and whether
                      the run records a flag
    verdicts          the two verdicts check_request_eligibility gives for the
                      employee and the item, as of the tests' fixed date
    required_calls    tool calls the run must include
    forbidden_calls   tool calls the run must not include

A tool call lists only the arguments that matter. A required
flag_for_human_review names the employee but not the free-text request and
reason, and a forbidden call with no arguments forbids the tool whatever it is
passed.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from it_equipment.agent.request import EquipmentRequest
from it_equipment.config import REPO_ROOT

# Beside the employees and the policies the cases are about. Both the runner
# and the tests read it from here, so moving the file breaks the tests too.
CASES_FILE = REPO_ROOT / "data" / "eval_cases.json"


@dataclass(frozen=True)
class ExpectedOutcome:
    """How a correct run ends: the draft's decision, item and answered, and whether it flags."""

    decision: str
    item: str | None
    # None for an escalated or unprocessed request, which relays no verdict.
    answered: str | None
    flagged: bool


@dataclass(frozen=True)
class ExpectedVerdicts:
    """The two verdicts check_request_eligibility gives for the case's employee and item."""

    additional: str
    replacement: str


@dataclass(frozen=True)
class ToolCall:
    """A tool call a case requires or forbids: the tool, and the arguments that must match."""

    tool: str
    # Only these are compared. Any other argument the model passes, such as a
    # flag's request and reason, may be anything.
    arguments: dict[str, Any]


@dataclass(frozen=True)
class EvalCase:
    """One demo request, with what a correct run of the agent looks like."""

    case_id: str
    # What the case is meant to show, in words, e.g. "Not processed: unknown
    # employee." Printed with each run, never graded.
    summary: str
    request: EquipmentRequest
    expected: ExpectedOutcome
    # None when no employee has the id, so there are no verdicts to give.
    verdicts: ExpectedVerdicts | None
    required_calls: list[ToolCall]
    forbidden_calls: list[ToolCall]


def load_cases_from_json(path: str | Path) -> list[EvalCase]:
    """Read a JSON file of eval cases and return them, in the file's order.

    A missing field raises KeyError, so a typo in the file fails the test that
    loads it rather than an eval run.
    """
    text = Path(path).read_text(encoding="utf-8")
    records = json.loads(text)

    cases = []
    for record in records:
        cases.append(build_case(record))

    return cases


def build_case(record: dict) -> EvalCase:
    """Turn one record from the JSON file into an EvalCase."""
    expected = record["expected"]

    # null in the file means there are no verdicts: no employee has the id.
    verdicts = None
    if record["verdicts"] is not None:
        verdicts = ExpectedVerdicts(
            additional=record["verdicts"]["additional"],
            replacement=record["verdicts"]["replacement"],
        )

    return EvalCase(
        case_id=record["case_id"],
        summary=record["summary"],
        # The id and the words are kept together as the request the agent is
        # given, exactly as the command line would give it.
        request=EquipmentRequest(employee_id=record["employee_id"], text=record["request"]),
        expected=ExpectedOutcome(
            decision=expected["decision"],
            item=expected["item"],
            answered=expected["answered"],
            flagged=expected["flagged"],
        ),
        verdicts=verdicts,
        required_calls=build_tool_calls(record["required_calls"]),
        forbidden_calls=build_tool_calls(record["forbidden_calls"]),
    )


def build_tool_calls(records: list[dict]) -> list[ToolCall]:
    """Turn a list of tool-call records from the JSON file into ToolCalls."""
    calls = []
    for record in records:
        calls.append(ToolCall(tool=record["tool"], arguments=record["arguments"]))

    return calls
