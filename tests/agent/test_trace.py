"""Unit tests for how the agent's trace is laid out.

These call the printers and layout helpers directly, with literal values, so a
failure points at the layout itself rather than at the model or the server.
Printed output is read back with pytest's capsys. Expected output is written
out in full, so each test also shows the layout it checks.
"""

from it_equipment.agent.draft import Draft
from it_equipment.agent.request import EquipmentRequest
from it_equipment.agent.trace import (
    LINE_WIDTH,
    TraceStep,
    action_text,
    lines_under_label,
    print_draft,
    print_loop_heading,
    print_loop_stopped,
    print_python_flag_failed,
    print_python_flagged,
    print_step,
    print_user_query,
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


def test_pythons_flag_is_printed_with_its_id(capsys):
    print_python_flagged("5f0c6a8e-2b1d-4e7a-9c3f-8d2e1b0a7c64")

    assert capsys.readouterr().out == (
        "  Python sent the request to a person instead: "
        "flag id 5f0c6a8e-2b1d-4e7a-9c3f-8d2e1b0a7c64.\n"
    )


def test_a_failed_python_flag_is_printed_with_the_tools_error(capsys):
    error = "Error executing tool flag_for_human_review: \"No employee with id 'E999'\""

    print_python_flag_failed(error)

    assert capsys.readouterr().out == (
        "  Python could not send the request to a person: Error executing tool "
        'flag_for_human_review: "No\n'
        "  employee with id 'E999'\"\n"
    )


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
