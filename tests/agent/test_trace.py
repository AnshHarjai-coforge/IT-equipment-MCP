"""Unit tests for how the agent's trace is laid out.

These call the printers and layout helpers directly, with literal values, so a
failure points at the layout itself rather than at the model or the server.
Printed output is read back with pytest's capsys. Expected output is written
out in full, so each test also shows the layout it checks.
"""

from dataclasses import replace

from it_equipment.agent.draft import Draft
from it_equipment.agent.request import EquipmentRequest
from it_equipment.agent.review import Review
from it_equipment.agent.trace import (
    LINE_WIDTH,
    TraceStep,
    action_text,
    decision_in_words,
    lines_under_label,
    numbered_text,
    print_draft,
    print_final_answer,
    print_loop_heading,
    print_loop_stopped,
    print_policy_check,
    print_reflection,
    print_reflection_failed,
    print_reflection_skipped,
    print_step,
    print_user_query,
    revised_text,
    wrapped_lines_under_label,
)

PRIYA_REQUEST = EquipmentRequest(
    employee_id="E001",
    text="My laptop is 4 years old and slow, can I get a replacement?",
)

APPROVED_DRAFT = Draft(
    decision="approved",
    item="laptop",
    answered="replacement",
    message="Your request for a replacement laptop is approved.",
    reason="check_request_eligibility approved a replacement laptop for E001.",
    flag_id=None,
)


def test_the_user_query_shows_the_sender_and_the_request_in_quotes(capsys):
    print_user_query(PRIYA_REQUEST)

    assert capsys.readouterr().out == (
        "User query\n"
        "  From:           E001\n"
        '  Request:        "My laptop is 4 years old and slow, can I get a replacement?"\n'
    )


def test_the_loop_heading_follows_a_blank_line(capsys):
    print_loop_heading()

    assert capsys.readouterr().out == "\nStep 1: ReAct loop\n"


def test_a_step_prints_numbered_labels_with_the_values_in_one_column(capsys):
    step = TraceStep(
        number=1,
        thought="I need their role.",
        tool_name="get_employee_info",
        arguments={"employee_id": "E001"},
        observation='{\n  "role": "standard"\n}',
        is_error=False,
    )

    print_step(step)

    assert capsys.readouterr().out == (
        "  Thought 1:      I need their role.\n"
        '  Action 1:       get_employee_info(employee_id="E001")\n'
        "  Observation 1:  {\n"
        '                    "role": "standard"\n'
        "                  }\n"
    )


def test_a_two_digit_number_keeps_a_space_before_the_value(capsys):
    step = TraceStep(10, "Check again.", "get_employee_info", {"employee_id": "E001"}, "{}", False)

    print_step(step)

    assert "  Observation 10: {}\n" in capsys.readouterr().out


def test_a_missing_thought_is_printed_as_none_given(capsys):
    step = TraceStep(1, "", "get_employee_info", {"employee_id": "E001"}, "{}", False)

    print_step(step)

    assert "  Thought 1:      (none given)\n" in capsys.readouterr().out


def test_the_draft_prints_every_field_in_order(capsys):
    print_draft(APPROVED_DRAFT)

    assert capsys.readouterr().out == (
        "\n"
        "Draft after the ReAct loop\n"
        "  Decision:       approved\n"
        "  Item:           laptop\n"
        "  Answered:       replacement\n"
        "  Message:        Your request for a replacement laptop is approved.\n"
        "  Reason:         check_request_eligibility approved a replacement laptop for E001.\n"
        "  Flag id:        none\n"
    )


def test_empty_draft_fields_print_as_none(capsys):
    draft = Draft("escalated", None, None, "A person will review it.", "Unclear item.", "f-1")

    print_draft(draft)

    printed = capsys.readouterr().out
    assert "  Item:           none\n" in printed
    assert "  Answered:       none\n" in printed


def test_the_stopped_line_says_why_and_that_there_is_no_draft(capsys):
    print_loop_stopped("the model refused")

    assert capsys.readouterr().out == (
        "\n  The ReAct loop stopped: the model refused, so there is no draft.\n"
    )


def test_a_long_stopped_line_is_wrapped_within_the_line_width(capsys):
    print_loop_stopped(
        "the model stopped for a reason the agent does not handle (model_context_window_exceeded)"
    )

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) > 2
    for line in lines:
        assert len(line) <= LINE_WIDTH


def test_action_text_reads_like_a_function_call():
    text = action_text("check_request_eligibility", {"employee_id": "E001", "item": "laptop"})

    assert text == 'check_request_eligibility(employee_id="E001", item="laptop")'


def test_a_blank_line_in_the_text_has_no_trailing_spaces():
    text = lines_under_label("Message", "First paragraph.\n\nSecond paragraph.")

    assert text == "  Message:        First paragraph.\n\n                  Second paragraph."


def test_long_prose_is_wrapped_within_the_line_width():
    long_thought = "They hold one laptop that is four years old. " * 5

    lines = wrapped_lines_under_label("Thought 1", long_thought).splitlines()

    assert len(lines) > 1
    for line in lines:
        assert len(line) <= LINE_WIDTH


def test_the_models_own_line_breaks_are_kept_when_wrapping():
    text = wrapped_lines_under_label("Thought 1", "First, their role.\nThen, the laptop rules.")

    assert text == "  Thought 1:      First, their role.\n                  Then, the laptop rules."


FLAG_ID = "5f0c6a8e-2b1d-4e7a-9c3f-8d2e1b0a7c64"

# Daniel asked for two more monitors; the loop approved one more.
DANIELS_DRAFT = Draft(
    decision="approved",
    item="monitor",
    answered="additional",
    message="One more monitor is approved.",
    reason="The additional verdict approves one more monitor for E002.",
    flag_id=None,
)

DANIELS_REVIEWED = Draft(
    decision="escalated",
    item="monitor",
    answered=None,
    message="A person will review your request for two more monitors.",
    reason="The additional verdict covers one more monitor, and Daniel asked for two.",
    flag_id=None,
)


def test_a_skipped_reflection_says_there_is_no_draft(capsys):
    print_reflection_skipped()

    assert capsys.readouterr().out == (
        "\nStep 2: Reflection\n  Reflection skipped: there is no draft to review.\n"
    )


def test_a_failed_reflection_says_why_and_that_the_draft_was_not_reviewed(capsys):
    print_reflection_failed("the model refused")

    assert capsys.readouterr().out == (
        "\n"
        "Step 2: Reflection\n"
        "  Reflection could not be used: the model refused, so the draft was not reviewed.\n"
    )


def test_a_confirmed_review_prints_what_was_checked_and_no_revision(capsys):
    review = Review(
        assessment="confirmed",
        problems=[],
        checked="The decision is Observation 2's replacement verdict.",
        final=APPROVED_DRAFT,
    )

    print_reflection(APPROVED_DRAFT, review, APPROVED_DRAFT)

    assert capsys.readouterr().out == (
        "\n"
        "Step 2: Reflection\n"
        "  Assessment:     confirmed\n"
        "  Critique:       No problems found. "
        "The decision is Observation 2's replacement verdict.\n"
        "  Revised:        No revision: the draft stands.\n"
    )


def test_a_revised_review_prints_its_problems_and_each_changed_field(capsys):
    review = Review(
        assessment="revised",
        problems=["Daniel asked for two more monitors, and Observation 2 approves one more."],
        checked="The decision against the question asked.",
        final=DANIELS_REVIEWED,
    )

    print_reflection(DANIELS_DRAFT, review, DANIELS_REVIEWED)

    assert capsys.readouterr().out == (
        "\n"
        "Step 2: Reflection\n"
        "  Assessment:     revised\n"
        "  Critique:       1. Daniel asked for two more monitors, and Observation 2 approves one "
        "more.\n"
        "  Revised:        decision: approved → escalated\n"
        "                  answered: additional → none\n"
        "                  message: rewritten (the new text is in the Final answer)\n"
        "                  reason: rewritten (the new text is in the Final answer)\n"
    )


def test_a_confirmed_review_with_nothing_checked_says_only_no_problems_found(capsys):
    review = Review(assessment="confirmed", problems=[], checked=" ", final=APPROVED_DRAFT)

    print_reflection(APPROVED_DRAFT, review, APPROVED_DRAFT)

    assert "  Critique:       No problems found.\n" in capsys.readouterr().out


def test_an_unchanged_draft_stands():
    assert revised_text(APPROVED_DRAFT, APPROVED_DRAFT) == "No revision: the draft stands."


def test_a_changed_flag_id_shows_old_and_new():
    flagged = replace(DANIELS_REVIEWED, flag_id=FLAG_ID)

    assert revised_text(DANIELS_REVIEWED, flagged) == f"flag_id: none → {FLAG_ID}"


def test_the_policy_check_prints_its_result_under_step_3(capsys):
    print_policy_check("Passed. The decision is escalated.")

    assert capsys.readouterr().out == (
        "\nStep 3: Policy check (Python)\n  Result:         Passed. The decision is escalated.\n"
    )


def test_an_approved_final_answer_has_no_flag_id_line(capsys):
    print_final_answer(APPROVED_DRAFT)

    assert capsys.readouterr().out == (
        "\n"
        "Final answer\n"
        "  Decision:       Approved (replacement laptop)\n"
        "  Reason:         check_request_eligibility approved a replacement laptop for E001.\n"
        "  Message:        Your request for a replacement laptop is approved.\n"
    )


def test_an_escalated_final_answer_prints_its_flag_id(capsys):
    print_final_answer(replace(DANIELS_REVIEWED, flag_id=FLAG_ID))

    assert capsys.readouterr().out == (
        "\n"
        "Final answer\n"
        "  Decision:       Escalated to a person\n"
        f"  Flag id:        {FLAG_ID}\n"
        "  Reason:         The additional verdict covers one more monitor, and Daniel asked for "
        "two.\n"
        "  Message:        A person will review your request for two more monitors.\n"
    )


def test_each_decision_reads_in_words():
    denied = replace(APPROVED_DRAFT, decision="denied", answered="additional")
    not_processed = replace(APPROVED_DRAFT, decision="not_processed")

    assert decision_in_words(APPROVED_DRAFT) == "Approved (replacement laptop)"
    assert decision_in_words(denied) == "Denied (additional laptop)"
    assert decision_in_words(DANIELS_REVIEWED) == "Escalated to a person"
    assert decision_in_words(not_processed) == "Not processed"


def test_a_long_numbered_sentence_carries_on_under_its_first_word():
    sentence = "Flag id: the draft gives a flag id which this run did not receive."

    text = numbered_text([sentence], 40)

    assert text == "1. Flag id: the draft gives a flag id\n   which this run did not receive."


def test_no_sentences_are_written_as_none():
    assert numbered_text([], 80) == "none"


def test_a_blank_sentence_still_gets_its_number():
    assert numbered_text(["", "A problem."], 80) == "1. \n2. A problem."
