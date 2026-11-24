"""Prove that the MCP server works, by connecting to it as a client.

This is the check the lab asks for before any more tools are built: start the
server, run this, and confirm a real response comes back over the wire.

Run it in a second terminal, with the server already running:

    python -m it_equipment.server      # terminal 1
    python scripts/check_connection.py # terminal 2

It reads the same settings the server does, so the two cannot end up pointing
at different addresses. It is a proof script rather than library code, which is
why it lives in scripts/ and not in the package.
"""

import asyncio

from httpx2 import TransportError
from mcp import Client
from mcp.types import CallToolResult

from it_equipment.config import load_settings

# A real employee in data/employees.json, and an id that is deliberately absent.
KNOWN_EMPLOYEE_ID = "E001"
UNKNOWN_EMPLOYEE_ID = "E999"


def print_result(result: CallToolResult) -> None:
    """Print one tool result: the error flag, the data, and the text."""
    print(f"  is_error:           {result.is_error}")
    print(f"  structured_content: {result.structured_content}")

    for block in result.content:
        # A result can carry several blocks, and only text blocks have .text.
        if hasattr(block, "text"):
            print(f"  text:               {block.text}")


async def check(url: str) -> None:
    """Connect to the server, list its tools, then call one twice.

    Once with an employee who exists and once with one who does not, so a
    single run shows both the normal path and the error path.
    """
    async with Client(url) as client:
        print(f"Connected to {url}")
        print()

        # Step one: has the tool registered? This is what the lab asks to see
        # confirmed before any business logic is trusted.
        listed = await client.list_tools()
        print(f"Tools the server is offering ({len(listed.tools)}):")

        for tool in listed.tools:
            print(f"  - {tool.name}")
            print(f"      output schema: {tool.output_schema}")

        print()

        # Step two: the normal path. A real record, fetched over the wire.
        print(f"Calling get_employee_info({KNOWN_EMPLOYEE_ID!r}) - a known employee:")
        found = await client.call_tool("get_employee_info", {"employee_id": KNOWN_EMPLOYEE_ID})
        print_result(found)
        print()

        # Step three: the edge case the spec names. The request itself succeeds,
        # but the error flag is set and the message explains why. That is how
        # the agent will tell a missing employee from a broken connection.
        print(f"Calling get_employee_info({UNKNOWN_EMPLOYEE_ID!r}) - no such employee:")
        missing = await client.call_tool("get_employee_info", {"employee_id": UNKNOWN_EMPLOYEE_ID})
        print_result(missing)


def report_unreachable(url: str, reason: BaseException) -> None:
    """Explain that the server could not be reached, without a stack trace.

    The cause is almost always that the server has not been started, which
    deserves an instruction rather than a traceback.
    """
    print(f"Could not reach the MCP server at {url}")
    print(f"  {type(reason).__name__}: {reason}")
    print()
    print("Is it running? Start it in another terminal with:")
    print("  python -m it_equipment.server")


async def main() -> None:
    settings = load_settings()
    url = settings.mcp_url()

    try:
        await check(url)
    # The star in "except*" is doing the work. The client runs its network
    # tasks in the background, and that machinery wraps a failure in a group,
    # sometimes in a group inside a group. "except*" searches inside those
    # groups, so a transport error is caught however deeply it is buried, and
    # anything that is not one is left alone to crash with its full traceback.
    except* TransportError as unreachable:
        report_unreachable(url, unreachable.exceptions[0])

        # A failed check should fail the command too, so that running this from
        # a script or a pipeline cannot mistake it for success.
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
