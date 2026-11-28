"""The agent's trace: each step it ran, and how everything is printed.

Everything is printed as it happens, and in full, in the layout agreed for the
demo (plan.md section 6, "Demo output layout"):

    User query                     who sent the request, and their words
    Step 1: ReAct loop             Thought, Action and Observation, numbered
                                   across the whole loop
    Draft after the ReAct loop     the model's draft, field by field, or one
                                   line saying why there is none
    Step 2: Reflection             Assessment, Critique, and Revised: only the
                                   fields reflection changed
    Step 3: Policy check (Python)  whether the reviewed draft stands, and why
    Final answer                   what the employee gets

Nothing is shortened, so a screenshot of a run shows all of it. Every value starts in
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

from it_equipment.agent.draft import DRAFT_FIELDS, Draft
from it_equipment.agent.request import EquipmentRequest
from it_equipment.agent.review import Review

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


def print_reflection_skipped() -> None:
    """Print Step 2 when the loop ended without a draft: there is nothing to review."""
    print()
    print("Step 2: Reflection")
    print(wrapped_line("Reflection skipped: there is no draft to review."))


def print_reflection_failed(why: str) -> None:
    """Print Step 2 when reflection's reply could not be used, saying why.

    For example: "Reflection could not be used: the model refused, so the
    draft was not reviewed."
    """
    print()
    print("Step 2: Reflection")
    print(wrapped_line(f"Reflection could not be used: {why}, so the draft was not reviewed."))


def print_reflection(draft: Draft, review: Review, reviewed: Draft) -> None:
    """Print Step 2: the review's assessment, its critique, and what it changed.

    What changed is worked out by comparing the draft with the reviewed draft,
    field by field, so the new text is printed once, in the Final answer.
    """
    print()
    print("Step 2: Reflection")
    print(lines_under_label("Assessment", review.assessment))
    print(lines_under_label("Critique", critique_text(review)))
    print(lines_under_label("Revised", revised_text(draft, reviewed)))


def print_policy_check(result: str) -> None:
    """Print Step 3: the Python check's result, as one or two sentences."""
    print()
    print("Step 3: Policy check (Python)")
    print(wrapped_lines_under_label("Result", result))


def print_final_answer(final: Draft) -> None:
    """Print the answer the employee gets: the decision in words, its reason and the message.

    The flag id is printed only for an escalated answer, the only kind that
    has one.
    """
    print()
    print("Final answer")
    print(lines_under_label("Decision", decision_in_words(final)))
    if final.decision == "escalated":
        print(lines_under_label("Flag id", text_or_none(final.flag_id)))
    print(wrapped_lines_under_label("Reason", final.reason))
    print(wrapped_lines_under_label("Message", final.message))


def critique_text(review: Review) -> str:
    """Return the review's problems numbered, or "No problems found." and what was checked.

    Wrapped to the room after the value column, ready to go under its label.
    """
    room = LINE_WIDTH - VALUE_COLUMN

    if len(review.problems) > 0:
        return numbered_text(review.problems, room)

    text = "No problems found."
    if review.checked.strip() != "":
        # What reflection checked is the reason a confirmed draft holds.
        text = f"{text} {review.checked.strip()}"

    return textwrap.fill(text, width=room)


def revised_text(draft: Draft, reviewed: Draft) -> str:
    """Return a line for each field reflection changed, or that the draft stands.

    A short field reads "decision: approved → escalated". The message and the
    reason are too long to show twice, so they read "rewritten", and their new
    text is printed once, in the Final answer.
    """
    before = draft.to_dict()
    after = reviewed.to_dict()

    lines = []
    for name in DRAFT_FIELDS:
        if before[name] == after[name]:
            continue

        if name == "message" or name == "reason":
            lines.append(f"{name}: rewritten (the new text is in the Final answer)")
        else:
            lines.append(f"{name}: {text_or_none(before[name])} → {text_or_none(after[name])}")

    if len(lines) == 0:
        return "No revision: the draft stands."

    return "\n".join(lines)


def decision_in_words(final: Draft) -> str:
    """Return the final decision in words, e.g. "Approved (replacement laptop)"."""
    if final.decision == "approved":
        return f"Approved ({text_or_none(final.answered)} {text_or_none(final.item)})"

    if final.decision == "denied":
        return f"Denied ({text_or_none(final.answered)} {text_or_none(final.item)})"

    if final.decision == "escalated":
        return "Escalated to a person"

    return "Not processed"


def numbered_text(sentences: list[str], width: int) -> str:
    """Return sentences as a numbered list, wrapped within width; "none" when there are none.

    A sentence too long for one line carries on under its own first word,
    not under the number, so each item reads as one block:

        1. Decision: expected escalated; the final answer says denied.
        2. Required call not made: get_employee_info(employee_id="E003").
    """
    if len(sentences) == 0:
        return "none"

    lines = []
    number = 0
    for sentence in sentences:
        number = number + 1
        label = f"{number}. "
        pieces = textwrap.wrap(sentence, width=width - len(label))
        if len(pieces) == 0:
            # A blank sentence wraps to nothing, and still needs its number.
            pieces = [""]
        lines.append(label + pieces[0])
        for piece in pieces[1:]:
            lines.append(" " * len(label) + piece)

    return "\n".join(lines)


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
