"""Handling one request from start to finish.

In plain words:

    1. Print the User query: who sent the request, and what they wrote.
    2. Run the ReAct loop, which prints each step as it runs.
    3. Print the model's draft. If the loop ended without one, say why, and
       have Python send the request to a person.

Python escalates a request with no draft because the model gave no decision
to relay: it refused, was cut off, or used up its calls. When in doubt a
person decides (plan decision 9). Branch 7 adds reflection and the Python check
between the draft and the final answer.
"""

from anthropic import AsyncAnthropicFoundry

from it_equipment.agent.mcp_bridge import Client, flag_id_from_result, observation_text
from it_equipment.agent.react_loop import LoopResult, run_react_loop
from it_equipment.agent.request import EquipmentRequest
from it_equipment.agent.trace import (
    print_draft,
    print_loop_stopped,
    print_python_flag_failed,
    print_python_flagged,
    print_user_query,
)


async def handle_request(
    model_client: AsyncAnthropicFoundry,
    mcp_client: Client,
    model: str,
    max_tokens: int,
    max_steps: int,
    request: EquipmentRequest,
) -> LoopResult:
    """Handle one request, printing everything as it happens, and return how the loop ended."""
    print_user_query(request)

    result = await run_react_loop(model_client, mcp_client, model, max_tokens, max_steps, request)

    if result.draft is not None:
        print_draft(result.draft)
    else:
        print_loop_stopped(result.stopped_because)
        await escalate_without_draft(mcp_client, request, result.stopped_because)

    return result


async def escalate_without_draft(
    mcp_client: Client, request: EquipmentRequest, stopped_because: str
) -> None:
    """Send a request the loop ended without deciding to a person, and print what happened.

    The flag goes through the server's own tool, as the model's would, so it
    lands in the same review queue with the same checks.
    """
    arguments = {
        "employee_id": request.employee_id,
        # The employee's words exactly as sent, so the reviewer reads what was
        # asked rather than anyone's summary of it.
        "request": request.text,
        "reason": f"The agent could not reach a decision: {stopped_because}.",
    }
    result = await mcp_client.call_tool("flag_for_human_review", arguments)

    if result.is_error:
        # The tool refuses an employee id that does not exist, and records
        # nothing. Its error says so, and is shown rather than hidden.
        print_python_flag_failed(observation_text(result))
    else:
        print_python_flagged(flag_id_from_result(result))
