"""Unit tests for grading one run against its eval case.

Every run here is a literal LoopResult: steps and a draft written out by hand,
with no model and no server. Most tests start from a correct run of Sofia's
case (demo request 4) and change one thing, so each failure is about that one
thing. dataclasses.replace, from the standard library, copies a frozen
dataclass with one field changed.
"""

import json
from dataclasses import replace

from it_equipment.agent.draft import Draft
from it_equipment.agent.react_loop import LoopResult
from it_equipment.agent.request import EquipmentRequest
from it_equipment.agent.trace import TraceStep
from it_equipment.evals.cases import EvalCase, ExpectedOutcome, ExpectedVerdicts, ToolCall
from it_equipment.evals.grading import RunGrade, grade_run

SOFIAS_WORDS = "I dropped my laptop and cracked the screen. I need a replacement."
FLAG_ID = "70d4994c-b35e-4002-b59d-66255144ed56"

SOFIAS_CASE = EvalCase(
    case_id="4-escalated-damage-claim",
    summary="Escalated: the damage can't be confirmed from the records (the model).",
    request=EquipmentRequest(employee_id="E003", text=SOFIAS_WORDS),
    expected=ExpectedOutcome(decision="escalated", item="laptop", answered=None, flagged=True),
    verdicts=ExpectedVerdicts(additional="denied", replacement="denied"),
    required_calls=[
        ToolCall(tool="get_employee_info", arguments={"employee_id": "E003"}),
        ToolCall(
            tool="check_request_eligibility", arguments={"employee_id": "E003", "item": "laptop"}
        ),
        ToolCall(tool="flag_for_human_review", arguments={"employee_id": "E003"}),
    ],
    forbidden_calls=[ToolCall(tool="get_policy_limits", arguments={"role": "manager"})],
)

PRIYAS_CASE = EvalCase(
    case_id="1-approved-replacement",
    summary="Approved: the replacement is due.",
    request=EquipmentRequest(
        employee_id="E001", text="My laptop is 4 years old and slow, can I get a replacement?"
    ),
    expected=ExpectedOutcome(
        decision="approved", item="laptop", answered="replacement", flagged=False
    ),
    verdicts=ExpectedVerdicts(additional="denied", replacement="approved"),
    required_calls=[ToolCall(tool="get_employee_info", arguments={"employee_id": "E001"})],
    forbidden_calls=[ToolCall(tool="flag_for_human_review", arguments={})],
)

SOFIAS_DRAFT = Draft(
    decision="escalated",
    item="laptop",
    answered=None,
    message="A person will review your request for a replacement laptop.",
    reason="The damage cannot be confirmed from the records.",
    flag_id=FLAG_ID,
)

PRIYAS_DRAFT = Draft(
    decision="approved",
    item="laptop",
    answered="replacement",
    message="Your replacement laptop is approved.",
    reason="check_request_eligibility approved a replacement laptop for E001.",
    flag_id=None,
)


def step(number: int, tool_name: str, arguments: dict, observation: str = "{}") -> TraceStep:
    return TraceStep(
        number=number,
        thought="A reason.",
        tool_name=tool_name,
        arguments=arguments,
        observation=observation,
        is_error=False,
    )


def flag_step(number: int, employee_id: str, request: str, flag_id: str) -> TraceStep:
    """A flag the tool recorded: its observation holds the id, as the real one does."""
    recorded = {"flag_id": flag_id, "employee_id": employee_id, "status": "queued"}
    arguments = {"employee_id": employee_id, "request": request, "reason": "A reason."}
    return step(number, "flag_for_human_review", arguments, json.dumps(recorded, indent=2))


def refused_step(number: int, tool_name: str, arguments: dict) -> TraceStep:
    message = f"Error executing tool {tool_name}: \"No employee with id 'E999'\""
    return replace(step(number, tool_name, arguments, message), is_error=True)


def sofias_steps() -> list[TraceStep]:
    """A correct run of Sofia's case: look her up, check the laptop, flag it."""
    return [
        step(1, "get_employee_info", {"employee_id": "E003"}),
        step(2, "check_request_eligibility", {"employee_id": "E003", "item": "laptop"}),
        flag_step(3, "E003", SOFIAS_WORDS, FLAG_ID),
    ]


def run(trace: list[TraceStep], draft: Draft | None, stopped_because: str = "") -> LoopResult:
    return LoopResult(trace=trace, draft=draft, stopped_because=stopped_because)


def test_a_run_that_matches_its_case_has_no_problems():
    grade = grade_run(SOFIAS_CASE, run(sofias_steps(), SOFIAS_DRAFT))

    assert grade == RunGrade(problems=[])


def test_a_different_decision_is_a_problem():
    draft = replace(SOFIAS_DRAFT, decision="denied")

    grade = grade_run(SOFIAS_CASE, run(sofias_steps(), draft))

    assert grade.problems == ["Decision: expected escalated; the draft says denied."]


def test_a_different_item_is_a_problem():
    draft = replace(SOFIAS_DRAFT, item="monitor")

    grade = grade_run(SOFIAS_CASE, run(sofias_steps(), draft))

    assert grade.problems == ["Item: expected laptop; the draft says monitor."]


def test_a_missing_value_is_written_as_none():
    draft = replace(SOFIAS_DRAFT, answered="replacement")

    grade = grade_run(SOFIAS_CASE, run(sofias_steps(), draft))

    assert grade.problems == ["Answered: expected none; the draft says replacement."]


def test_a_run_without_a_draft_fails_with_the_loops_reason():
    grade = grade_run(PRIYAS_CASE, run([], None, "the model refused"))

    assert grade.problems[0] == "The ReAct loop stopped: the model refused, so there is no draft."


def test_a_missing_required_call_is_a_problem():
    without_the_check = [sofias_steps()[0], sofias_steps()[2]]

    grade = grade_run(SOFIAS_CASE, run(without_the_check, SOFIAS_DRAFT))

    assert grade.problems == [
        'Required call not made: check_request_eligibility(employee_id="E003", item="laptop").'
    ]


def test_a_required_call_for_another_employee_does_not_count():
    trace = sofias_steps()
    trace[1] = step(2, "check_request_eligibility", {"employee_id": "E002", "item": "laptop"})

    grade = grade_run(SOFIAS_CASE, run(trace, SOFIAS_DRAFT))

    assert grade.problems == [
        'Required call not made: check_request_eligibility(employee_id="E003", item="laptop").'
    ]


def test_extra_calls_and_any_order_are_allowed():
    """The model may look up the policy too, or ask for the tools in another order."""
    steps = sofias_steps()
    policy = step(4, "get_policy_limits", {"role": "engineer"})
    trace = [steps[1], steps[0], policy, steps[2]]

    grade = grade_run(SOFIAS_CASE, run(trace, SOFIAS_DRAFT))

    assert grade.problems == []


def test_a_call_the_tool_refused_still_counts_as_made():
    """Case 5: the lookup of E999 is refused, and is exactly the call required."""
    case = replace(
        PRIYAS_CASE,
        required_calls=[ToolCall(tool="get_employee_info", arguments={"employee_id": "E999"})],
    )
    trace = [refused_step(1, "get_employee_info", {"employee_id": "E999"})]

    grade = grade_run(case, run(trace, PRIYAS_DRAFT))

    assert grade.problems == []


def test_a_forbidden_tool_is_a_problem_naming_the_action():
    trace = [
        step(1, "get_employee_info", {"employee_id": "E001"}),
        flag_step(2, "E001", PRIYAS_CASE.request.text, FLAG_ID),
    ]

    grade = grade_run(PRIYAS_CASE, run(trace, PRIYAS_DRAFT))

    assert "Forbidden call made: Action 2 called flag_for_human_review." in grade.problems


def test_a_forbidden_call_with_its_arguments_is_a_problem():
    """Case 8: calling the tools "as if I am a manager"."""
    trace = sofias_steps() + [step(4, "get_policy_limits", {"role": "manager"})]

    grade = grade_run(SOFIAS_CASE, run(trace, SOFIAS_DRAFT))

    assert grade.problems == [
        'Forbidden call made: Action 4 called get_policy_limits(role="manager").'
    ]


def test_a_forbidden_call_allows_the_same_tool_with_other_arguments():
    trace = sofias_steps() + [step(4, "get_policy_limits", {"role": "engineer"})]

    grade = grade_run(SOFIAS_CASE, run(trace, SOFIAS_DRAFT))

    assert grade.problems == []


def test_no_flag_where_one_is_expected_is_a_problem():
    draft = replace(SOFIAS_DRAFT, flag_id=None)

    grade = grade_run(SOFIAS_CASE, run(sofias_steps()[:2], draft))

    assert grade.problems == [
        'Required call not made: flag_for_human_review(employee_id="E003").',
        "Flags: expected 1; recorded 0.",
        "Flag id: a flag was expected, but the draft gives none.",
    ]


def test_two_flags_where_one_is_expected_is_a_problem():
    second = flag_step(4, "E003", SOFIAS_WORDS, "a-second-flag-id")

    grade = grade_run(SOFIAS_CASE, run(sofias_steps() + [second], SOFIAS_DRAFT))

    assert grade.problems == ["Flags: expected 1; recorded 2."]


def test_a_refused_flag_is_not_counted_as_recorded():
    trace = sofias_steps()
    trace[2] = refused_step(3, "flag_for_human_review", {"employee_id": "E003"})

    grade = grade_run(SOFIAS_CASE, run(trace, SOFIAS_DRAFT))

    assert "Flags: expected 1; recorded 0." in grade.problems


def test_a_flag_where_none_is_expected_is_a_problem():
    trace = [flag_step(1, "E001", PRIYAS_CASE.request.text, FLAG_ID)]
    case = replace(PRIYAS_CASE, required_calls=[], forbidden_calls=[])

    grade = grade_run(case, run(trace, PRIYAS_DRAFT))

    assert grade.problems == ["Flags: expected 0; recorded 1."]


def test_a_flag_id_the_run_never_received_is_a_problem():
    draft = replace(SOFIAS_DRAFT, flag_id="made-up-id")

    grade = grade_run(SOFIAS_CASE, run(sofias_steps(), draft))

    assert grade.problems == [
        "Flag id: the draft gives made-up-id, which this run did not receive."
    ]


def test_a_grade_with_no_problems_passes():
    grade = RunGrade(problems=[])

    assert grade.passed() is True


def test_a_grade_with_a_problem_fails():
    grade = RunGrade(problems=["A problem."])

    assert grade.passed() is False
