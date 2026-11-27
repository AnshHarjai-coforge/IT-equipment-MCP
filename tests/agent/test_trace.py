"""Unit tests for how the agent's trace is laid out.

These call the printers and layout helpers directly, with literal values, so a
failure points at the layout itself rather than at the model or the server.
Printed output is read back with pytest's capsys.
"""

from it_equipment.agent.trace import (
    LINE_WIDTH,
    TraceStep,
    action_text,
    lines_under_label,
    print_step,
    wrapped_lines_under_label,
)


def test_print_step_lines_the_values_up_in_one_column(capsys):
    step = TraceStep(
        thought="I need her role.",
        tool_name="get_employee_info",
        arguments={"employee_id": "E001"},
        observation='{\n  "role": "standard"\n}',
        is_error=False,
    )

    print_step(step)

    assert capsys.readouterr().out == (
        "  Thought:     I need her role.\n"
        '  Action:      get_employee_info(employee_id="E001")\n'
        "  Observation: {\n"
        '                 "role": "standard"\n'
        "               }\n"
    )


def test_a_missing_thought_is_printed_as_none_given(capsys):
    step = TraceStep("", "get_employee_info", {"employee_id": "E001"}, "{}", False)

    print_step(step)

    assert "  Thought:     (none given)\n" in capsys.readouterr().out


def test_action_text_reads_like_a_function_call():
    text = action_text("check_request_eligibility", {"employee_id": "E001", "item": "laptop"})

    assert text == 'check_request_eligibility(employee_id="E001", item="laptop")'


def test_a_blank_line_in_the_text_has_no_trailing_spaces():
    text = lines_under_label("Text", "First paragraph.\n\nSecond paragraph.")

    assert text == "  Text:        First paragraph.\n\n               Second paragraph."


def test_long_prose_is_wrapped_within_the_line_width():
    long_thought = "She holds one laptop that is four years old. " * 5

    lines = wrapped_lines_under_label("Thought", long_thought).splitlines()

    assert len(lines) > 1
    for line in lines:
        assert len(line) <= LINE_WIDTH


def test_the_models_own_line_breaks_are_kept_when_wrapping():
    text = wrapped_lines_under_label("Thinking", "First, her role.\nThen, the laptop rules.")

    assert text == "  Thinking:    First, her role.\n               Then, the laptop rules."
