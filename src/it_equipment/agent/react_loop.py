"""The ReAct loop: the model calls tools until it writes its draft, or the loop stops.

In plain words, each pass round the loop is one call to the model:

    1. Send the conversation so far, with the tools and the draft's schema.
    2. If the model has finished (end_turn), read its draft and stop.
    3. If it asked for tools (tool_use), run each one in the order asked,
       print its Thought, Action and Observation, and send every result back
       in one message. Then go round again.
    4. Anything else, such as a refusal or a reply cut off, stops the loop
       without a draft, with a sentence saying why.

The loop also stops, without a draft, once it has made max_steps calls to the
model. What happens to a request with no draft is the caller's decision.

This module imports nothing from mcp: the tools and results are converted in
mcp_bridge.py.
"""

from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropicFoundry
from anthropic.types import Message, ToolUseBlock

from it_equipment.agent.draft import DRAFT_FORMAT, Draft, InvalidDraftError, draft_from_reply
from it_equipment.agent.mcp_bridge import (
    Client,
    arguments_without_thought,
    claude_tools_from_server,
    observation_text,
    thought_from_arguments,
)
from it_equipment.agent.prompts import SYSTEM_PROMPT
from it_equipment.agent.request import EquipmentRequest
from it_equipment.agent.trace import TraceStep, print_loop_heading, print_step


@dataclass(frozen=True)
class LoopResult:
    """How the loop ended: every step it ran, and the draft, or why there is none."""

    trace: list[TraceStep]
    # None when the loop stopped without a draft; stopped_because then says why.
    draft: Draft | None
    # Why the loop stopped without a draft, as words to print, e.g. "the model
    # refused". Empty when there is a draft.
    stopped_because: str


async def run_react_loop(
    model_client: AsyncAnthropicFoundry,
    mcp_client: Client,
    model: str,
    max_tokens: int,
    max_steps: int,
    request: EquipmentRequest,
) -> LoopResult:
    """Run the ReAct loop for one request, printing each step, and return how it ended.

    Takes the three settings it uses rather than all of them.
    """
    print_loop_heading()

    tools = await claude_tools_from_server(mcp_client)
    messages = [{"role": "user", "content": request.prompt_text()}]
    trace = []

    # One pass is one call to the model, so max_steps passes is the limit.
    # The pass number itself is not needed, hence the underscore.
    for _ in range(max_steps):
        # These six are sent and nothing else. thinking is left out, so the
        # model thinks as it does by default and no summary is asked for: the
        # Thought on each tool call is the reasoning the trace shows.
        reply = await model_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            output_config={"format": DRAFT_FORMAT},
        )

        # The reply goes back exactly as it came. The API refuses a thinking
        # block that has been changed, and the model's tool calls must still
        # hold the thoughts it wrote.
        messages.append({"role": "assistant", "content": reply.content})

        if reply.stop_reason == "end_turn":
            # The model asked for no more tools, so this reply is its draft.
            try:
                draft = draft_from_reply(reply)
            except InvalidDraftError:
                return LoopResult(
                    trace=trace,
                    draft=None,
                    stopped_because="the model's final reply could not be read as a draft",
                )

            return LoopResult(trace=trace, draft=draft, stopped_because="")

        if reply.stop_reason != "tool_use":
            # A refusal, or a reply cut off: not something to guess past.
            return LoopResult(
                trace=trace,
                draft=None,
                stopped_because=why_the_model_stopped(reply.stop_reason, max_tokens),
            )

        tool_calls = tool_calls_in_reply(reply)
        if len(tool_calls) == 0:
            # A reply must answer every tool call with a result, so a reply
            # that claims to call tools but names none leaves nothing to send.
            return LoopResult(
                trace=trace,
                draft=None,
                stopped_because="the model said it would call a tool but asked for none",
            )

        tool_results = []
        for tool_call in tool_calls:
            # Numbered across the whole loop, so this is one more than the
            # steps already run.
            step = await run_tool_call(mcp_client, tool_call, len(trace) + 1)
            trace.append(step)

            print()
            print_step(step)

            tool_results.append(tool_result_block(tool_call.id, step))

        # Every result goes back in one message, in the order the model asked,
        # each paired with its call by the call's id.
        messages.append({"role": "user", "content": tool_results})

    return LoopResult(
        trace=trace,
        draft=None,
        stopped_because=f"it reached the limit of {max_steps} calls to the model",
    )


async def run_tool_call(mcp_client: Client, tool_call: ToolUseBlock, number: int) -> TraceStep:
    """Run one tool call on the server, without its thought, and return it as a step."""
    # The thought is the agent's own field, not the server's, so the server
    # is called without it. A new dictionary is made for that, leaving the
    # model's tool call untouched for when it goes back to the model.
    arguments = arguments_without_thought(tool_call.input)
    result = await mcp_client.call_tool(tool_call.name, arguments)

    return TraceStep(
        number=number,
        thought=thought_from_arguments(tool_call.input),
        tool_name=tool_call.name,
        arguments=arguments,
        observation=observation_text(result),
        is_error=result.is_error,
    )


def tool_result_block(tool_use_id: str, step: TraceStep) -> dict[str, Any]:
    """Return the block that hands one tool's result back to the model.

    The content is the same text the trace prints, so the trace shows exactly
    what the model was given. is_error tells the model the tool could not
    answer, as for an unknown employee id.
    """
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": step.observation,
        "is_error": step.is_error,
    }


def tool_calls_in_reply(reply: Message) -> list[ToolUseBlock]:
    """Return the tool calls in a reply, in the order the model asked for them."""
    tool_calls = []
    for block in reply.content:
        if block.type == "tool_use":
            tool_calls.append(block)

    return tool_calls


def why_the_model_stopped(stop_reason: str | None, max_tokens: int) -> str:
    """Return, as words to print, why the model stopped without a draft or a tool call."""
    if stop_reason == "refusal":
        return "the model refused"

    if stop_reason == "max_tokens":
        return f"the model's reply was cut off at the limit of {max_tokens} tokens"

    if stop_reason == "model_context_window_exceeded":
        return "the conversation grew too long for the model to read"

    # pause_turn and stop_sequence cannot happen here: the agent declares no
    # server tools and sends no stop sequences. Should one arrive, or a stop
    # reason added to the API later, its name is shown rather than hidden.
    return f"the model stopped for a reason the agent does not handle ({stop_reason})"
