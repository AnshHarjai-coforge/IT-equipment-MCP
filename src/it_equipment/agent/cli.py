"""The agent's command line: opens both clients, runs the agent, and reports failures plainly.

A failure the user can fix (the server is not running, Foundry refused the
call) is explained in a line or two rather than a stack trace, and the program
exits with status 1 so a script running it can tell it failed.
"""

from anthropic import APIError, AsyncAnthropicFoundry
from httpx2 import TransportError

from it_equipment.agent.first_call import HARDCODED_REQUEST, NoToolCallError, run_first_tool_call
from it_equipment.agent.mcp_bridge import connect_to_server
from it_equipment.config import load_settings


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
