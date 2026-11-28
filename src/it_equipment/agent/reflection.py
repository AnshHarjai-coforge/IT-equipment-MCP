"""Reflection: one call to the model, with no tools, to review the loop's draft.

In plain words:

    1. Write one message holding the request, every Action with its
       Observation exactly as the model was given it, and the draft. The
       Thoughts are left out (plan decision 18): the reviewer judges the
       draft against the evidence, not against the agent's own reasoning.
    2. Send it with the reviewer prompt and the review's schema, and no
       tools, so reflection cannot change anything on the server.
    3. Read the review back. If the model refused, was cut off, or wrote
       something that is not a review, raise ReflectionFailedError saying
       why, so the caller can send the request to a person instead.

Reflection is not a step of the loop: it does not count towards max_steps.
"""

import json

from anthropic import AsyncAnthropicFoundry

from it_equipment.agent.draft import Draft
from it_equipment.agent.prompts import REVIEWER_PROMPT
from it_equipment.agent.react_loop import why_the_model_stopped
from it_equipment.agent.request import EquipmentRequest
from it_equipment.agent.review import REVIEW_FORMAT, InvalidReviewError, Review, review_from_reply
from it_equipment.agent.trace import TraceStep, action_text


class ReflectionFailedError(Exception):
    """Raised when reflection's reply cannot be used.

    The message says why, as words to print, e.g. "the model refused", the
    same words the loop uses when it stops without a draft.
    """


async def reflect(
    model_client: AsyncAnthropicFoundry,
    model: str,
    max_tokens: int,
    request: EquipmentRequest,
    trace: list[TraceStep],
    draft: Draft,
) -> Review:
    """Ask the model to review the draft against the evidence, and return its review.

    Raises ReflectionFailedError if the model stops for any reason other than
    finishing (a refusal, a reply cut off at max_tokens), or if what it wrote
    cannot be read as a review.
    """
    # These five are sent and nothing else. There are no tools, so reflection
    # can only read; thinking and effort are left out, as in the loop.
    reply = await model_client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=REVIEWER_PROMPT,
        messages=[{"role": "user", "content": review_prompt_text(request, trace, draft)}],
        output_config={"format": REVIEW_FORMAT},
    )

    if reply.stop_reason != "end_turn":
        # The same words the loop prints for the same stop reasons.
        raise ReflectionFailedError(why_the_model_stopped(reply.stop_reason, max_tokens))

    try:
        return review_from_reply(reply)
    except InvalidReviewError as error:
        raise ReflectionFailedError("the model's reply could not be read as a review") from error


def review_prompt_text(request: EquipmentRequest, trace: list[TraceStep], draft: Draft) -> str:
    """Return the one message reflection is sent: the request, the evidence, and the draft.

    For Priya's request it starts:

        Employee E001 sent this request:

        <employee_request>
        My laptop is 4 years old and slow, can I get a replacement?
        </employee_request>

        The tool calls the agent made, in order, with exactly what each returned:

        Action 1: get_employee_info(employee_id="E001")
        Observation 1:
        {

    then gives each Observation in full, then the draft as JSON.
    """
    # The request exactly as the loop was given it, so the employee's words
    # sit inside the same tags and the reviewer is told the same about them.
    lines = [request.prompt_text(), ""]

    if len(trace) == 0:
        lines.append("The agent made no tool calls.")
        lines.append("")
    else:
        lines.append("The tool calls the agent made, in order, with exactly what each returned:")
        lines.append("")
        for step in trace:
            # Numbered as in the trace, so a problem can name "Observation 2"
            # and a person can find it in the printed run. No Thought.
            lines.append(f"Action {step.number}: {action_text(step.tool_name, step.arguments)}")
            lines.append(f"Observation {step.number}:")
            lines.append(step.observation)
            lines.append("")

    lines.append("The agent's draft:")
    lines.append("")
    # Indented like the Observations, and with the employee's own characters
    # kept as they are.
    lines.append(json.dumps(draft.to_dict(), indent=2, ensure_ascii=False))

    return "\n".join(lines)
