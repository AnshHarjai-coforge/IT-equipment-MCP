"""Grading one run of the agent against its eval case.

What is graded is the final answer: what the employee gets, after reflection
and the Python check. In plain words, a run passes when all four of these hold:

    1. The final answer's decision, item and answered are the case's, exactly.
    2. Every required call was made. Other calls are allowed, and so is any
       order, so the model may also call get_policy_limits, or ask for
       several tools in one reply.
    3. No forbidden call was made.
    4. One flag was recorded when the case expects one, and none otherwise,
       and any flag id the final answer gives is one this run received.

A run that ends the loop without a draft fails the first check, whatever
Python did next: the agent reached no decision of its own. The calls checked
in 2 and 3 are the model's own Actions. A flag counted in 4 may be the
model's or the one Python made, since either puts the request in front of a
person.

The message text is not graded: judging it is reflection's job. Everything
here is pure. It reads a case and a handled request and returns sentences, so
each check is tested with literal results and no model.
"""

import json
from dataclasses import dataclass

from it_equipment.agent.draft import Draft
from it_equipment.agent.handler import HandledRequest
from it_equipment.agent.trace import TraceStep, action_text, text_or_none
from it_equipment.evals.cases import EvalCase, ExpectedOutcome, ToolCall

FLAG_TOOL = "flag_for_human_review"


@dataclass(frozen=True)
class RunGrade:
    """What grading found in one run: the problems that fail it, in check order."""

    problems: list[str]

    def passed(self) -> bool:
        """Return True when the run has no problems."""
        return len(self.problems) == 0


def grade_run(case: EvalCase, handled: HandledRequest) -> RunGrade:
    """Return what grading found in one run of the agent on this case, problems in check order."""
    loop = handled.loop
    flag_ids = flag_ids_received(loop.trace, handled.python_flag_id)

    problems = []

    if loop.draft is None:
        # The same sentence the trace printed when the loop stopped. The final
        # answer is then Python's, not the agent's, so it is not compared.
        problems.append(f"The ReAct loop stopped: {loop.stopped_because}, so there is no draft.")
    else:
        problems.extend(final_answer_problems(case.expected, handled.final))

    problems.extend(missing_call_problems(case.required_calls, loop.trace))
    problems.extend(forbidden_call_problems(case.forbidden_calls, loop.trace))
    problems.extend(flag_problems(case.expected.flagged, handled.final.flag_id, flag_ids))

    return RunGrade(problems=problems)


def final_answer_problems(expected: ExpectedOutcome, final: Draft) -> list[str]:
    """Return a sentence for each of decision, item and answered that differs from the case."""
    problems = []

    if final.decision != expected.decision:
        problems.append(
            f"Decision: expected {expected.decision}; the final answer says {final.decision}."
        )

    # text_or_none writes a missing value as "none", as the answer is printed.
    if final.item != expected.item:
        problems.append(
            f"Item: expected {text_or_none(expected.item)}; "
            f"the final answer says {text_or_none(final.item)}."
        )

    if final.answered != expected.answered:
        problems.append(
            f"Answered: expected {text_or_none(expected.answered)}; "
            f"the final answer says {text_or_none(final.answered)}."
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


def flag_problems(
    expected_flagged: bool, final_flag_id: str | None, flag_ids: list[str]
) -> list[str]:
    """Return what is wrong with the flags: how many were recorded, and the answer's flag id."""
    # One flag, because the tool and the system prompt both say to call it
    # once per request, and Python reuses a flag the run already recorded: a
    # second flag is a duplicate for a person to sort out.
    expected_count = 0
    if expected_flagged:
        expected_count = 1

    problems = []

    if len(flag_ids) != expected_count:
        problems.append(f"Flags: expected {expected_count}; recorded {len(flag_ids)}.")

    if final_flag_id is None:
        if expected_flagged:
            problems.append("Flag id: a flag was expected, but the final answer gives none.")
    elif final_flag_id not in flag_ids:
        # An id the run never received was made up, or copied from elsewhere.
        problems.append(
            f"Flag id: the final answer gives {final_flag_id}, which this run did not receive."
        )

    return problems


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


def flag_ids_received(trace: list[TraceStep], python_flag_id: str | None) -> list[str]:
    """Return the id of every flag the run recorded: the loop's in order, then Python's.

    A refused flag records nothing and has no id, so it is not counted.
    """
    flag_ids = []
    for step in trace:
        if step.tool_name == FLAG_TOOL and not step.is_error:
            # A recorded flag's observation is the tool's dictionary as JSON,
            # which holds the id the tool made.
            recorded = json.loads(step.observation)
            flag_ids.append(recorded["flag_id"])

    if python_flag_id is not None:
        flag_ids.append(python_flag_id)

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
