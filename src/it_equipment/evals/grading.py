"""Grading one run of the agent against its eval case.

In plain words, a run passes when all four of these hold:

    1. The draft's decision, item and answered are the case's, exactly.
    2. Every required call was made. Other calls are allowed, and so is any
       order, so the model may also call get_policy_limits, or ask for
       several tools in one reply.
    3. No forbidden call was made.
    4. One flag was recorded when the case expects one, and none otherwise,
       and any flag id the draft gives is one this run received.

A run that ends without a draft fails the first check, whatever Python did
next: the agent reached no decision of its own.

One finding is a warning rather than a failure: a flag whose request is not
the employee's words exactly. The tool asks for their own words, but the
outcome is the same either way.

The message text is not graded: judging it is reflection's job (branch 7).
Everything here is pure. It reads a case and a loop's result and returns
sentences, so each check is tested with literal results and no model.
"""

import json
from dataclasses import dataclass

from it_equipment.agent.draft import Draft
from it_equipment.agent.react_loop import LoopResult
from it_equipment.agent.trace import TraceStep, action_text, text_or_none
from it_equipment.evals.cases import EvalCase, ExpectedOutcome, ToolCall

FLAG_TOOL = "flag_for_human_review"


@dataclass(frozen=True)
class RunGrade:
    """What grading found in one run: the problems that fail it, and the warnings that do not."""

    problems: list[str]
    warnings: list[str]

    def passed(self) -> bool:
        """Return True when the run has no problems. Warnings do not fail a run."""
        return len(self.problems) == 0


def grade_run(case: EvalCase, result: LoopResult) -> RunGrade:
    """Return what grading found in one run of the agent on this case, problems in check order."""
    problems = []
    problems.extend(draft_problems(case.expected, result.draft, result.stopped_because))
    problems.extend(missing_call_problems(case.required_calls, result.trace))
    problems.extend(forbidden_call_problems(case.forbidden_calls, result.trace))
    problems.extend(flag_problems(case.expected.flagged, result.draft, result.trace))

    warnings = flag_request_warnings(case.request.text, result.trace)

    return RunGrade(problems=problems, warnings=warnings)


def draft_problems(
    expected: ExpectedOutcome, draft: Draft | None, stopped_because: str
) -> list[str]:
    """Return a sentence for each of decision, item and answered that differs from the case."""
    if draft is None:
        # The same sentence the trace printed when the loop stopped.
        return [f"The ReAct loop stopped: {stopped_because}, so there is no draft."]

    problems = []

    if draft.decision != expected.decision:
        problems.append(f"Decision: expected {expected.decision}; the draft says {draft.decision}.")

    # text_or_none writes a missing value as "none", as the draft is printed.
    if draft.item != expected.item:
        problems.append(
            f"Item: expected {text_or_none(expected.item)}; "
            f"the draft says {text_or_none(draft.item)}."
        )

    if draft.answered != expected.answered:
        problems.append(
            f"Answered: expected {text_or_none(expected.answered)}; "
            f"the draft says {text_or_none(draft.answered)}."
        )

    return problems


def missing_call_problems(required_calls: list[ToolCall], trace: list[TraceStep]) -> list[str]:
    """Return a sentence for each required call that no step of the run matches."""
    problems = []
    for call in required_calls:
        if len(steps_matching(call, trace)) == 0:
            problems.append(f"Required call not made: {call_text(call)}.")

    return problems


def forbidden_call_problems(forbidden_calls: list[ToolCall], trace: list[TraceStep]) -> list[str]:
    """Return a sentence, naming the Action, for each step that matches a forbidden call."""
    problems = []
    for call in forbidden_calls:
        for step in steps_matching(call, trace):
            problems.append(f"Forbidden call made: Action {step.number} called {call_text(call)}.")

    return problems


def flag_problems(expected_flagged: bool, draft: Draft | None, trace: list[TraceStep]) -> list[str]:
    """Return what is wrong with the flags: how many were recorded, and the draft's flag id."""
    flag_ids = flag_ids_received(trace)

    # One flag, because the tool and the system prompt both say to call it
    # once per request: a second flag is a duplicate for a person to sort out.
    expected_count = 0
    if expected_flagged:
        expected_count = 1

    problems = []

    if len(flag_ids) != expected_count:
        problems.append(f"Flags: expected {expected_count}; recorded {len(flag_ids)}.")

    if draft is None:
        # The missing draft is already a problem, and there is no flag id to check.
        return problems

    if draft.flag_id is None:
        if expected_flagged:
            problems.append("Flag id: a flag was expected, but the draft gives none.")
    elif draft.flag_id not in flag_ids:
        # An id the run never received was made up, or copied from elsewhere.
        problems.append(
            f"Flag id: the draft gives {draft.flag_id}, which this run did not receive."
        )

    return problems


def flag_request_warnings(request_text: str, trace: list[TraceStep]) -> list[str]:
    """Return a warning for each flag whose request is not the employee's words exactly."""
    warnings = []
    for step in trace:
        if step.tool_name != FLAG_TOOL:
            continue

        # The server's schema requires a request, so a call without one was
        # refused and is already an error; there is nothing to compare.
        if "request" not in step.arguments:
            continue

        if step.arguments["request"] != request_text:
            warnings.append(f"Action {step.number}'s request is not the employee's words exactly.")

    return warnings


def steps_matching(call: ToolCall, trace: list[TraceStep]) -> list[TraceStep]:
    """Return the steps of the run that match a case's tool call, in the order they ran.

    A step matches when it called the same tool and every argument the case
    lists has the same value. Arguments the case does not list are not looked
    at. Whether the tool answered or refused does not matter: case 5's lookup
    of E999 is refused, and is still the call the case requires.
    """
    matching = []
    for step in trace:
        if step_matches(call, step):
            matching.append(step)

    return matching


def step_matches(call: ToolCall, step: TraceStep) -> bool:
    """Return True when the step called the case's tool with every argument the case lists."""
    if step.tool_name != call.tool:
        return False

    for name in call.arguments:
        if name not in step.arguments:
            return False
        if step.arguments[name] != call.arguments[name]:
            return False

    return True


def flag_ids_received(trace: list[TraceStep]) -> list[str]:
    """Return the id of every flag the run recorded, in the order recorded.

    A refused flag records nothing and has no id, so it is not counted.
    """
    flag_ids = []
    for step in trace:
        if step.tool_name == FLAG_TOOL and not step.is_error:
            # A recorded flag's observation is the tool's dictionary as JSON,
            # which holds the id the tool made.
            recorded = json.loads(step.observation)
            flag_ids.append(recorded["flag_id"])

    return flag_ids


def call_text(call: ToolCall) -> str:
    """Return a case's tool call as words, e.g. get_employee_info(employee_id="E001").

    A call that lists no arguments is just the tool's name, since it matches
    the tool whatever it is passed, and "flag_for_human_review()" would read as
    a call with no arguments at all.
    """
    if len(call.arguments) == 0:
        return call.tool

    return action_text(call.tool, call.arguments)
