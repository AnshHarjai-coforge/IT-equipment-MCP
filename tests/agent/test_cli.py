"""Unit tests for the agent's command line.

main() itself opens a real model client and a real MCP connection, so it is
checked by hand rather than here. What is tested is the logic it relies on.
"""

from it_equipment.agent.cli import first_exception_inside
from it_equipment.agent.first_call import NoToolCallError


def test_first_exception_inside_finds_an_error_two_groups_deep():
    """How an error raised inside the MCP client's block arrives."""
    error = NoToolCallError("end_turn", "")
    wrapped = ExceptionGroup("outer", [ExceptionGroup("inner", [error])])

    found = first_exception_inside(wrapped)

    assert found is error


def test_first_exception_inside_finds_an_error_one_group_deep():
    """How a refused connection arrives."""
    error = ConnectionRefusedError("All connection attempts failed")

    found = first_exception_inside(ExceptionGroup("only", [error]))

    assert found is error
