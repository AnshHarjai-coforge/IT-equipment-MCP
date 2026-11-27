"""The agent: hands an equipment request to the model and runs the tool it asks for.

So far it makes one call to the model, for one hardcoded request, and runs the
first tool the model asks for. The ReAct loop comes next and builds on the
pieces here.

Everything the model does is printed as it happens, and in full: the summary
of its thinking, any text it writes, every tool call it asks for with the
Thought it gave, and what came back. Nothing is shortened, so a screenshot of a
run shows all of it.

This module imports nothing from mcp. The MCP client is made, and its tools
and results are taken apart, in agent_tools.py.

Run it in a second terminal, with the server already running:

    python -m it_equipment.server   # terminal 1
    python -m it_equipment.agent    # terminal 2

It reads the Foundry key, the resource name and the deployment name from .env
by itself. Never source .env into a terminal: Claude Code reads
ANTHROPIC_MODEL as well, and would pick up the deployment name as its own.
"""

import asyncio
import json
import textwrap
from dataclasses import dataclass
from typing import Any

from anthropic import APIError, AsyncAnthropicFoundry
from anthropic.types import Message, ToolUseBlock
from dotenv import load_dotenv
from httpx2 import TransportError

from it_equipment.agent_tools import (
    Client,
    arguments_without_thought,
    claude_tools_from_server,
    connect_to_server,
    observation_text,
    thought_from_arguments,
)
from it_equipment.config import REPO_ROOT, load_settings
from it_equipment.prompts import SYSTEM_PROMPT

# Demo request 1, from Priya (E001). The id sits outside the quotes because it
# comes from who sent the request, never from what they wrote.
HARDCODED_REQUEST = (
    'Employee E001 sent this request: "My laptop is 4 years old and slow, can I get a replacement?"'
)

# Opus 5 thinks before it replies whether or not this is sent, and adaptive is
# what it does by default. "summarized" asks the API to send back a summary of
# that thinking, so the trace can show it; without it the text is left out.
THINKING = {"type": "adaptive", "display": "summarized"}

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


class NoToolCallError(Exception):
    """Raised when the model's reply holds no tool call that can be run.

    The model may have answered in text instead, refused, or been cut off.
    Raising rather than returning None means a caller cannot mistake "no tool
    was called" for a step that ran.
    """

    def __init__(self, stop_reason: str | None, text: str) -> None:
        # Both are kept, so whoever catches this can see why the model stopped
        # and what it said instead.
        self.stop_reason = stop_reason
        self.text = text
        super().__init__(f"The model's reply has no tool call to run (stop reason: {stop_reason}).")


async def run_first_tool_call(
    model_client: AsyncAnthropicFoundry,
    mcp_client: Client,
    model: str,
    max_tokens: int,
    request_text: str,
) -> TraceStep:
    """Send the request to the model once, run the first tool it asks for, and return that step.

    Each part is printed as it happens: the request, the model's reply, the
    tool call with its result, and then any further tool calls the model asked
    for, which are shown but not run. The result is printed, not sent back to
    the model.

    Takes the model's name and the reply limit rather than all of the
    settings, because those are the only two settings it uses.

    Raises NoToolCallError if the reply holds no tool call to run.
    """
    print_request(request_text)

    tools = await claude_tools_from_server(mcp_client)

    # Only these six are sent, and everything else is left at its default.
    # temperature, top_p and top_k are not among them because the API version
    # this SDK speaks no longer has them.
    reply = await model_client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        thinking=THINKING,
        tools=tools,
        messages=[{"role": "user", "content": request_text}],
    )
    print_model_reply(reply)

    tool_calls = tool_calls_in_reply(reply)

    # "tool_use" is the only stop reason that means the model finished asking
    # for tools. A reply cut off at max_tokens can hold a tool call whose
    # arguments were never finished, which is not something to run.
    if reply.stop_reason != "tool_use" or len(tool_calls) == 0:
        raise NoToolCallError(reply.stop_reason, text_in_reply(reply))

    first_call = tool_calls[0]
    arguments = arguments_without_thought(first_call.input)
    result = await mcp_client.call_tool(first_call.name, arguments)

    step = TraceStep(
        thought=thought_from_arguments(first_call.input),
        tool_name=first_call.name,
        arguments=arguments,
        observation=observation_text(result),
        is_error=result.is_error,
    )

    print()
    print(f"Tool call 1 of {len(tool_calls)}")
    print_step(step)

    print_tool_calls_not_run(tool_calls)

    return step


def tool_calls_in_reply(reply: Message) -> list[ToolUseBlock]:
    """Return the tool calls in a reply, in the order the model asked for them."""
    tool_calls = []
    for block in reply.content:
        if block.type == "tool_use":
            tool_calls.append(block)

    return tool_calls


def text_in_reply(reply: Message) -> str:
    """Return the text the model wrote in a reply, or "" if it wrote none.

    Thinking is left out: this is what the model said, not how it got there.
    """
    texts = []
    for block in reply.content:
        if block.type == "text":
            texts.append(block.text)

    return "\n".join(texts)


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


def first_exception_inside(group: BaseExceptionGroup) -> BaseException:
    """Return the first exception in a group that is not itself a group.

    The MCP client wraps an error raised inside its block in a group, and that
    group in another one. except* recognises the error inside, but hands back
    the wrapping with it, so this takes the first item one layer at a time
    until it reaches the error itself, however many layers there are.
    """
    error = group
    while isinstance(error, BaseExceptionGroup):
        error = error.exceptions[0]

    return error


def report_unreachable(url: str, reason: BaseException) -> None:
    """Explain that the MCP server could not be reached, without a stack trace.

    The same words check_connection.py uses. The cause is almost always that
    the server has not been started, which deserves an instruction rather than
    a traceback.
    """
    print(f"Could not reach the MCP server at {url}")
    print(f"  {type(reason).__name__}: {reason}")
    print()
    print("Is it running? Start it in another terminal with:")
    print("  python -m it_equipment.server")


def report_model_failure(reason: BaseException) -> None:
    """Explain that the call to the model failed, without a stack trace.

    The usual causes are a mistyped resource or deployment name, or a key
    Foundry refuses. The message is the SDK's own: the status code and
    Foundry's reply, which never include the key.
    """
    print()
    print(f"The model call failed: {type(reason).__name__}: {reason}")
    print()
    print("Check ANTHROPIC_FOUNDRY_RESOURCE, ANTHROPIC_FOUNDRY_API_KEY and ANTHROPIC_MODEL.")


async def main() -> None:
    settings = load_settings()
    url = settings.mcp_url()

    try:
        # The model client is opened first. It reads its own key from the
        # environment, and with none it fails right here, before any
        # connection is made, with the SDK's own error: that names the variable
        # to set and holds no key. None of the handlers below catches it.
        async with AsyncAnthropicFoundry() as model_client:
            async with connect_to_server(url) as mcp_client:
                await run_first_tool_call(
                    model_client,
                    mcp_client,
                    settings.model,
                    settings.max_tokens,
                    HARDCODED_REQUEST,
                )
    # "except*" for the reason check_connection.py gives: the MCP client wraps
    # a failure in a group, often a group inside a group, and "except*" looks
    # inside. Python does not allow "except" and "except*" on the same try,
    # so all three are written this way.
    except* TransportError as unreachable:
        report_unreachable(url, first_exception_inside(unreachable))

        # A failed run should fail the command too, so a script or a pipeline
        # running it cannot mistake it for success.
        raise SystemExit(1)
    except* NoToolCallError as no_tool_call:
        print()
        print(first_exception_inside(no_tool_call))
        raise SystemExit(1)
    except* APIError as model_failure:
        report_model_failure(first_exception_inside(model_failure))
        raise SystemExit(1)


if __name__ == "__main__":
    # .env is read here and nowhere else. Loading it inside load_settings would
    # let a real .env leak into the tests; here it reaches only this process.
    # The file beside config.toml is named outright, rather than left to
    # python-dotenv's own search upwards from this file. A variable already
    # set in the environment wins over .env, which is python-dotenv's default.
    load_dotenv(REPO_ROOT / ".env")
    asyncio.run(main())
