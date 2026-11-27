"""Unit tests for the agent's command line.

main() itself opens a real model client and a real MCP connection, so it is
checked by hand rather than here. What is tested is the logic it relies on:
reading the request from the command line, and unwrapping exception groups.
"""

import pytest

from it_equipment.agent.cli import first_exception_inside, request_from_command_line
from it_equipment.agent.request import EquipmentRequest

PRIYA_TEXT = "My laptop is 4 years old and slow, can I get a replacement?"


def test_the_id_and_the_words_become_the_request():
    request = request_from_command_line(["E001", PRIYA_TEXT])

    assert request == EquipmentRequest(employee_id="E001", text=PRIYA_TEXT)


def test_the_words_are_kept_exactly_as_typed():
    request = request_from_command_line(["E001", "  I’d like a dock.  "])

    assert request.text == "  I’d like a dock.  "


def test_a_missing_request_exits_with_status_2(capsys):
    with pytest.raises(SystemExit) as stopped:
        request_from_command_line(["E001"])

    assert stopped.value.code == 2
    assert "the following arguments are required: request" in capsys.readouterr().err


def test_a_blank_request_exits_with_status_2(capsys):
    with pytest.raises(SystemExit) as stopped:
        request_from_command_line(["E001", "   "])

    assert stopped.value.code == 2
    assert "error: the request is blank" in capsys.readouterr().err


def test_first_exception_inside_finds_an_error_two_groups_deep():
    """How an error raised inside the MCP client's block arrives."""
    error = RuntimeError("raised inside the block")
    wrapped = ExceptionGroup("outer", [ExceptionGroup("inner", [error])])

    found = first_exception_inside(wrapped)

    assert found is error


def test_first_exception_inside_finds_an_error_one_group_deep():
    """How a refused connection arrives."""
    error = ConnectionRefusedError("All connection attempts failed")

    found = first_exception_inside(ExceptionGroup("only", [error]))

    assert found is error
