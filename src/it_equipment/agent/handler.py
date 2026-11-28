"""Handling one request from start to finish.

In plain words:

    1. Print the User query: who sent the request, and what they wrote.
    2. Step 1, the ReAct loop, which prints each step as it runs. Then print
       the draft, or the line saying why there is none.
    3. Step 2, reflection: a second call to the model, with no tools,
       reviews the draft against the evidence, and confirms or corrects it.
    4. Step 3, the Python check: the reviewed draft stands only if this run's
       tool results back it (policy_check.py).
    5. Print the final answer.

Python sends the request to a person itself whenever there is no answer it
can stand behind: the loop ended without a draft, reflection could not be
used, or the check failed. When in doubt a person decides (plan decision 9).
It also makes the flag for an escalated answer that has none yet, such as one
reflection escalated. If the run already recorded a flag for the sender,
Python uses that one, so a request is never flagged twice.

Python's flags go through the server's own tool, as the model's do, so they
land in the same review queue with the same checks.
"""

from dataclasses import dataclass, replace

from anthropic import AsyncAnthropicFoundry

from it_equipment.agent.draft import Draft
from it_equipment.agent.mcp_bridge import (
    CallToolResult,
    Client,
    flag_id_from_result,
    observation_text,
)
from it_equipment.agent.policy_check import check_reviewed_draft, recorded_flag_id
from it_equipment.agent.react_loop import LoopResult, run_react_loop
from it_equipment.agent.reflection import ReflectionFailedError, reflect
from it_equipment.agent.request import EquipmentRequest
from it_equipment.agent.review import reviewed_draft
from it_equipment.agent.trace import (
    print_draft,
    print_final_answer,
    print_loop_stopped,
    print_policy_check,
    print_reflection,
    print_reflection_failed,
    print_reflection_skipped,
    print_user_query,
)


@dataclass(frozen=True)
class HandledRequest:
    """What happened to one request: how the loop ended, the final answer, and Python's flag."""

    loop: LoopResult
    # The answer the employee gets, after reflection and the Python check.
    final: Draft
    # The flag Python recorded itself, or None. The model's own flags are
    # among the loop's steps.
    python_flag_id: str | None


async def handle_request(
    model_client: AsyncAnthropicFoundry,
    mcp_client: Client,
    model: str,
    max_tokens: int,
    max_steps: int,
    request: EquipmentRequest,
) -> HandledRequest:
    """Handle one request, printing everything as it happens, and return what happened."""
    print_user_query(request)

    loop = await run_react_loop(model_client, mcp_client, model, max_tokens, max_steps, request)

    handled = await answer_after_loop(model_client, mcp_client, model, max_tokens, request, loop)

    print_final_answer(handled.final)
    return handled


async def answer_after_loop(
    model_client: AsyncAnthropicFoundry,
    mcp_client: Client,
    model: str,
    max_tokens: int,
    request: EquipmentRequest,
    loop: LoopResult,
) -> HandledRequest:
    """Return the final answer: reflection, then the Python check, then any flag Python makes.

    Prints the draft, Step 2 and Step 3 as each happens.
    """
    # A flag the model already recorded for the sender, which Python uses
    # rather than making a second one if it has to escalate.
    existing_flag_id = recorded_flag_id(request.employee_id, loop.trace)

    if loop.draft is None:
        print_loop_stopped(loop.stopped_because)
        print_reflection_skipped()
        return await escalated_by_python(
            mcp_client,
            request,
            loop,
            item=None,
            reason=f"The agent could not reach a decision: {loop.stopped_because}.",
            result_opening="Not checked: there is no draft.",
            existing_flag_id=existing_flag_id,
        )

    print_draft(loop.draft)

    try:
        review = await reflect(model_client, model, max_tokens, request, loop.trace, loop.draft)
    except ReflectionFailedError as failure:
        # Nobody has checked the draft's wording, so it is not sent.
        print_reflection_failed(str(failure))
        return await escalated_by_python(
            mcp_client,
            request,
            loop,
            item=loop.draft.item,
            reason=f"The agent's draft could not be reviewed: {failure}.",
            result_opening="Not checked: reflection could not review the draft, so it is not sent.",
            existing_flag_id=existing_flag_id,
        )

    reviewed = reviewed_draft(loop.draft, review)
    print_reflection(loop.draft, review, reviewed)

    check = check_reviewed_draft(request.employee_id, loop.trace, reviewed)

    if not check.passed:
        return await escalated_by_python(
            mcp_client,
            request,
            loop,
            item=reviewed.item,
            reason=f"The Python check failed. {check.explanation}",
            result_opening=f"Failed. {check.explanation}",
            existing_flag_id=check.flag_id,
        )

    if reviewed.decision != "escalated":
        print_policy_check(f"Passed. {check.explanation}")
        # Only an escalated answer has a flag id, and it always comes from
        # the tool's own result, never from the model's text.
        return HandledRequest(loop=loop, final=replace(reviewed, flag_id=None), python_flag_id=None)

    if check.flag_id is not None:
        print_policy_check(f"Passed. {check.explanation}")
        # An escalated answer relays no verdict, so answered is none.
        final = replace(reviewed, answered=None, flag_id=check.flag_id)
        return HandledRequest(loop=loop, final=final, python_flag_id=None)

    # Escalated with no flag yet, as when reflection escalated the draft, so
    # Python records it, with the reviewed draft's own reason. A blank reason
    # would be refused by the tool, so one is written for it.
    reason = reviewed.reason
    if reason.strip() == "":
        reason = "The agent escalated the request."

    result = await send_to_a_person(mcp_client, request, reason)
    if result.is_error:
        error = observation_text(result)
        print_policy_check(
            f"Passed. {check.explanation} Python could not send the request to a person: {error}"
        )
        return HandledRequest(
            loop=loop,
            final=not_processed_answer(request, reviewed.item, error),
            python_flag_id=None,
        )

    flag_id = flag_id_from_result(result)
    print_policy_check(
        f"Passed. {check.explanation} Python sent the request to a person: flag id {flag_id}."
    )
    final = replace(reviewed, answered=None, flag_id=flag_id)
    return HandledRequest(loop=loop, final=final, python_flag_id=flag_id)


async def escalated_by_python(
    mcp_client: Client,
    request: EquipmentRequest,
    loop: LoopResult,
    item: str | None,
    reason: str,
    result_opening: str,
    existing_flag_id: str | None,
) -> HandledRequest:
    """Send the request to a person in Python's own words, print Step 3, and return the answer.

    Used when there is no answer Python can stand behind. The message is
    Python's, not the model's, because the model's may say "approved". A flag
    the run already recorded for the sender is used rather than a second one.
    """
    if existing_flag_id is not None:
        print_policy_check(
            f"{result_opening} The request goes to a person with the flag this run already "
            f"recorded: flag id {existing_flag_id}."
        )
        final = escalated_answer(item, reason, existing_flag_id)
        return HandledRequest(loop=loop, final=final, python_flag_id=None)

    result = await send_to_a_person(mcp_client, request, reason)
    if result.is_error:
        error = observation_text(result)
        print_policy_check(
            f"{result_opening} Python could not send the request to a person: {error}"
        )
        return HandledRequest(
            loop=loop, final=not_processed_answer(request, item, error), python_flag_id=None
        )

    flag_id = flag_id_from_result(result)
    print_policy_check(f"{result_opening} Python sent the request to a person: flag id {flag_id}.")
    return HandledRequest(
        loop=loop, final=escalated_answer(item, reason, flag_id), python_flag_id=flag_id
    )


async def send_to_a_person(
    mcp_client: Client, request: EquipmentRequest, reason: str
) -> CallToolResult:
    """Call flag_for_human_review for the sender, and return the tool's result."""
    arguments = {
        "employee_id": request.employee_id,
        # The employee's words exactly as sent, so the reviewer reads what was
        # asked rather than anyone's summary of it.
        "request": request.text,
        "reason": reason,
    }
    return await mcp_client.call_tool("flag_for_human_review", arguments)


def escalated_answer(item: str | None, reason: str, flag_id: str) -> Draft:
    """Return the answer Python gives when it sends a request to a person, in its own words."""
    return Draft(
        decision="escalated",
        item=item,
        answered=None,
        message=(
            f"Your request has been passed to a person to review, under reference {flag_id}. "
            "They will get back to you."
        ),
        reason=reason,
        flag_id=flag_id,
    )


def not_processed_answer(request: EquipmentRequest, item: str | None, error: str) -> Draft:
    """Return the answer when even Python's flag is refused.

    Only an unknown employee id makes the tool refuse here: the request is
    never blank, and Python always writes a reason. So the employee is asked
    to check their id, as the agent would for an unknown id.
    """
    return Draft(
        decision="not_processed",
        item=item,
        answered=None,
        message=(
            f"No employee has the id {request.employee_id}, so your request could not be "
            "processed. Please check your employee id and send the request again."
        ),
        reason=f"Python could not send the request to a person: {error}",
        flag_id=None,
    )
