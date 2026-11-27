"""The agent's trace: each step it ran, and how everything is printed.

Everything the model does is printed as it happens, and in full: the summary
of its thinking, any text it writes, every tool call it asks for with the
Thought it gave, and what came back. Nothing is shortened, so a screenshot of a
run shows all of it.

TraceStep lives here, beside print_step, rather than with the code that makes
the steps. That code imports these printers, so if TraceStep lived there too
each module would import the other, which Python cannot start.
"""

import json
import textwrap
from dataclasses import dataclass
from typing import Any

from anthropic.types import Message, ToolUseBlock

from it_equipment.agent.mcp_bridge import arguments_without_thought, thought_from_arguments

# Where every printed value starts, so the values line up in one column. It is
# the width of the longest label, "  Observation: ".
VALUE_COLUMN = 15

# No printed line of prose runs past this, which suits a terminal and a
# screenshot. JSON is never wrapped, because breaking it would change its shape.
LINE_WIDTH = 100


@dataclass(frozen=True)
class TraceStep:
    """One Action the agent ran: the model's reason, the tool call, and what came back."""

    thought: str
    tool_name: str
    # Without the thought, so exactly what the server was called with.
    arguments: dict[str, Any]
    # The tool result as text: the same text the model reads.
    observation: str
    # True when the tool could not answer, such as for an unknown employee id.
    is_error: bool


def print_request(request_text: str) -> None:
    """Print the request the model is about to be given."""
    print("Request")
    print(
        textwrap.fill(request_text, width=LINE_WIDTH, initial_indent="  ", subsequent_indent="  ")
    )


def print_model_reply(reply: Message) -> None:
    """Print what the model wrote in its reply: its thinking summary and its text.

    The reply's tool calls are printed separately, each with what came of it.
    """
    print()
    print(f"Model reply  (stop reason: {reply.stop_reason})")

    for block in reply.content:
        if block.type == "thinking":
            # Empty when the API sends no summary, and then there is nothing
            # to show.
            if block.thinking != "":
                print(wrapped_lines_under_label("Thinking", block.thinking))
        elif block.type == "redacted_thinking":
            # Thinking the API sends back only in encrypted form. Saying so
            # keeps the trace honest about a part it cannot show.
            print(lines_under_label("Thinking", "(redacted by the API, so it cannot be shown)"))
        elif block.type == "text":
            print(wrapped_lines_under_label("Text", block.text))


def print_step(step: TraceStep) -> None:
    """Print one step as Thought, Action and Observation, with the values lined up."""
    print_thought_and_action(step.thought, step.tool_name, step.arguments)
    print(lines_under_label("Observation", step.observation))


def print_tool_calls_not_run(tool_calls: list[ToolUseBlock]) -> None:
    """Print every tool call after the first, each marked as not run.

    The model may ask for several tools in one reply. Only the first is run
    for now, but the rest are still shown in full, so the trace hides nothing
    the model asked for.
    """
    position = 2
    for tool_call in tool_calls[1:]:
        print()
        print(
            f"Tool call {position} of {len(tool_calls)}  (not run: this branch runs only the first)"
        )
        print_thought_and_action(
            thought_from_arguments(tool_call.input),
            tool_call.name,
            arguments_without_thought(tool_call.input),
        )
        position = position + 1


def print_thought_and_action(thought: str, tool_name: str, arguments: dict[str, Any]) -> None:
    """Print a tool call's Thought and its Action."""
    if thought == "":
        # The schema requires a thought, so an empty one means the model
        # ignored that. Saying so is clearer than a blank.
        thought = "(none given)"

    print(wrapped_lines_under_label("Thought", thought))
    print(lines_under_label("Action", action_text(tool_name, arguments)))


def action_text(tool_name: str, arguments: dict[str, Any]) -> str:
    """Return a tool call written as a function call, e.g. get_employee_info(employee_id="E001")."""
    parts = []
    for name in arguments:
        # json.dumps writes text in double quotes and numbers as they are, so
        # the call reads the way it would be typed. ensure_ascii=False keeps
        # an employee's own characters as they wrote them.
        value = json.dumps(arguments[name], ensure_ascii=False)
        parts.append(f"{name}={value}")

    joined = ", ".join(parts)
    return f"{tool_name}({joined})"


def label_padded_to_column(label: str) -> str:
    """Return a label followed by enough spaces to reach VALUE_COLUMN, e.g. "  Thought:     "."""
    return f"  {label}:".ljust(VALUE_COLUMN)


def lines_under_label(label: str, text: str) -> str:
    """Return text after its label, with each further line starting under the first.

    The text's own line breaks are kept, which is what indented JSON needs.
    """
    lines = text.splitlines()

    if len(lines) == 0:
        return f"  {label}:"

    indented = [label_padded_to_column(label) + lines[0]]
    for line in lines[1:]:
        if line == "":
            # A blank line stays blank, with no spaces left trailing on it.
            indented.append("")
        else:
            indented.append(" " * VALUE_COLUMN + line)

    return "\n".join(indented)


def wrapped_lines_under_label(label: str, text: str) -> str:
    """Return prose after its label, wrapped so that no line runs past LINE_WIDTH."""
    wrapped = []
    for line in text.splitlines():
        # Each of the model's own lines is wrapped on its own, so its
        # paragraphs and lists keep their shape instead of running together.
        if line.strip() == "":
            wrapped.append("")
        else:
            for piece in textwrap.wrap(line, width=LINE_WIDTH - VALUE_COLUMN):
                wrapped.append(piece)

    return lines_under_label(label, "\n".join(wrapped))
