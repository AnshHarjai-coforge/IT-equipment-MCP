"""The agent's command line: reads the request, opens both clients, and reports failures plainly.

Run it with the id of the employee who sent the request, then their words in
quotes:

    python -m it_equipment.agent E001 "My laptop is 4 years old and slow, can I get a replacement?"

A failure the user can fix (the server is not running, Foundry refused the
call) is explained in a line or two rather than a stack trace, and the program
exits with status 1 so a script running it can tell it failed.
"""

import argparse
import sys

from anthropic import APIError, AsyncAnthropicFoundry
from httpx2 import TransportError

from it_equipment.agent.handler import handle_request
from it_equipment.agent.mcp_bridge import connect_to_server
from it_equipment.agent.request import EquipmentRequest
from it_equipment.config import load_settings


def request_from_command_line(arguments: list[str]) -> EquipmentRequest:
    """Return the request given on the command line: the sender's id, then their words.

    A missing argument or a blank request prints the usage line and an error,
    and exits with status 2, which is argparse's own rule for a command used
    wrongly. A blank request is refused for the same reason
    flag_for_human_review refuses one: there is nothing to act on.
    """
    parser = argparse.ArgumentParser(
        prog="python -m it_equipment.agent",
        description="Handle one IT equipment request: the ReAct loop over the MCP server's tools.",
    )
    parser.add_argument(
        "employee_id", help="the id of the employee who sent the request, e.g. E001"
    )
    parser.add_argument("request", help="the employee's request in their own words, in quotes")

    parsed = parser.parse_args(arguments)

    if parsed.request.strip() == "":
        parser.error("the request is blank")

    return EquipmentRequest(employee_id=parsed.employee_id, text=parsed.request)


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
    # The command line is read first, so a mistyped command stops before any
    # connection is made. sys.argv[0] is the program's own name, so the
    # arguments start after it.
    request = request_from_command_line(sys.argv[1:])

    settings = load_settings()
    url = settings.mcp_url()

    try:
        # The model client is opened first. It reads its own key from the
        # environment, and with none it fails right here, before any
        # connection is made, with the SDK's own error: that names the variable
        # to set and holds no key. None of the handlers below catches it.
        async with AsyncAnthropicFoundry() as model_client:
            async with connect_to_server(url) as mcp_client:
                await handle_request(
                    model_client,
                    mcp_client,
                    settings.model,
                    settings.max_tokens,
                    settings.max_steps,
                    request,
                )
    # "except*" for the reason check_connection.py gives: the MCP client wraps
    # a failure in a group, often a group inside a group, and "except*" looks
    # inside. Python does not allow "except" and "except*" on the same try,
    # so both are written this way.
    except* TransportError as unreachable:
        report_unreachable(url, first_exception_inside(unreachable))

        # A failed run should fail the command too, so a script or a pipeline
        # running it cannot mistake it for success.
        raise SystemExit(1)
    except* APIError as model_failure:
        report_model_failure(first_exception_inside(model_failure))
        raise SystemExit(1)
