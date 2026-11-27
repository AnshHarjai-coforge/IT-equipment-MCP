"""The agent's first call: hands one hardcoded request to the model and runs the tool it asks for.

So far it makes one call to the model, for one hardcoded request, and runs the
first tool the model asks for. The ReAct loop comes next and builds on the
pieces here.

Each part is printed as it happens, by the printers in trace.py. This module
imports nothing from mcp: the MCP client is made, and its tools and results are
taken apart, in mcp_bridge.py.
"""

from anthropic import AsyncAnthropicFoundry
from anthropic.types import Message, ToolUseBlock

from it_equipment.agent.mcp_bridge import (
    Client,
    arguments_without_thought,
    claude_tools_from_server,
    observation_text,
    thought_from_arguments,
)
from it_equipment.agent.prompts import SYSTEM_PROMPT
from it_equipment.agent.trace import (
    TraceStep,
    print_model_reply,
    print_request,
    print_step,
    print_tool_calls_not_run,
)

# Demo request 1, from Priya (E001). The id sits outside the quotes because it
# comes from who sent the request, never from what they wrote.
HARDCODED_REQUEST = (
    'Employee E001 sent this request: "My laptop is 4 years old and slow, can I get a replacement?"'
)

# Opus 5 thinks before it replies whether or not this is sent, and adaptive is
# what it does by default. "summarized" asks the API to send back a summary of
# that thinking, so the trace can show it; without it the text is left out.
THINKING = {"type": "adaptive", "display": "summarized"}


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
        # The first call is the only one run, so it is always number 1.
        number=1,
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
