"""The agent's trace: each step it ran, and how everything is printed.

Everything is printed as it happens, and in full, in the layout agreed for the
demo (plan.md section 6, "Demo output layout"):

    User query                   who sent the request, and their words
    Step 1: ReAct loop           Thought, Action and Observation, numbered
                                 across the whole loop
    Draft after the ReAct loop   the model's draft, field by field

or, when the loop ends without a draft, one line saying why. Nothing is
shortened, so a screenshot of a run shows all of it. Every value starts in
the same column; prose wraps at LINE_WIDTH; JSON is never wrapped, so the
printed Observation is exactly what the model was given.

TraceStep lives here, beside print_step, rather than with the code that makes
the steps. That code imports these printers, so if TraceStep lived there too
each module would import the other, which Python cannot start.
"""

import json
import textwrap
from dataclasses import dataclass
from typing import Any

from anthropic.types import Message, ToolUseBlock

from it_equipment.agent.draft import Draft
from it_equipment.agent.mcp_bridge import arguments_without_thought, thought_from_arguments
from it_equipment.agent.request import EquipmentRequest

# Where every printed value starts, so the values line up in one column. It is
# the width of the longest label in a normal run, "  Observation 1:  ".
VALUE_COLUMN = 18

# No printed line of prose runs past this, which suits a terminal and a
# screenshot. JSON is never wrapped, because breaking it would change its shape.
LINE_WIDTH = 100


@dataclass(frozen=True)
class TraceStep:
    """One Action the agent ran: the model's reason, the tool call, and what came back."""

    # Counted across the whole loop, whichever reply the call came from, so
    # two calls from one reply are 1 and 2, as in the original ReAct paper.
    number: int
    thought: str
    tool_name: str
    # Without the thought, so exactly what the server was called with.
    arguments: dict[str, Any]
    # The tool result as text: the same text the model reads.
    observation: str
    # True when the tool could not answer, such as for an unknown employee id.
    is_error: bool


def print_user_query(request: EquipmentRequest) -> None:
    """Print who sent the request and what they wrote, in quotes, exactly as sent.

    The two are shown apart because the id comes from the sender, never from
    the text.
    """
    print("User query")
    print(lines_under_label("From", request.employee_id))
    print(wrapped_lines_under_label("Request", f'"{request.text}"'))


def print_loop_heading() -> None:
    """Print the heading the loop's steps are listed under."""
    print()
    print("Step 1: ReAct loop")


def print_step(step: TraceStep) -> None:
    """Print one step as Thought, Action and Observation, numbered, with the values lined up."""
    print_thought_and_action(step.number, step.thought, step.tool_name, step.arguments)
    print(lines_under_label(f"Observation {step.number}", step.observation))


def print_draft(draft: Draft) -> None:
    """Print the model's draft, one field per line, with an empty field shown as "none"."""
    print()
    print("Draft after the ReAct loop")
    print(lines_under_label("Decision", draft.decision))
    print(lines_under_label("Item", text_or_none(draft.item)))
    print(lines_under_label("Answered", text_or_none(draft.answered)))
    print(wrapped_lines_under_label("Message", draft.message))
    print(wrapped_lines_under_label("Reason", draft.reason))
    print(lines_under_label("Flag id", text_or_none(draft.flag_id)))


def print_loop_stopped(stopped_because: str) -> None:
    """Print the one line that ends the loop when there is no draft, saying why.

    For example: "The ReAct loop stopped: the model refused, so there is no
    draft."
    """
    print()
    print(wrapped_line(f"The ReAct loop stopped: {stopped_because}, so there is no draft."))


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
            position,
            thought_from_arguments(tool_call.input),
            tool_call.name,
            arguments_without_thought(tool_call.input),
        )
        position = position + 1


def print_thought_and_action(
    number: int, thought: str, tool_name: str, arguments: dict[str, Any]
) -> None:
    """Print a tool call's Thought and its Action, under the call's number."""
    if thought == "":
        # The schema requires a thought, so an empty one means the model
        # ignored that. Saying so is clearer than a blank.
        thought = "(none given)"

    print(wrapped_lines_under_label(f"Thought {number}", thought))
    print(lines_under_label(f"Action {number}", action_text(tool_name, arguments)))


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


def text_or_none(value: str | None) -> str:
    """Return the value, or "none" when there is none, which reads better than a blank."""
    if value is None:
        return "none"

    return value


def label_padded_to_column(label: str) -> str:
    """Return a label followed by enough spaces to reach VALUE_COLUMN, e.g. "  Thought 1:      ".

    The space after the colon is part of the label, so even a label as long as
    the column, such as "Observation 10", keeps one space before its value.
    """
    return f"  {label}: ".ljust(VALUE_COLUMN)


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


def wrapped_line(text: str) -> str:
    """Return a sentence indented under its section heading, wrapped within LINE_WIDTH."""
    return textwrap.fill(text, width=LINE_WIDTH, initial_indent="  ", subsequent_indent="  ")
