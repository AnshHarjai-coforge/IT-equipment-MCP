"""Prove that the MCP server works, by connecting to it as a client.

This began as the check the lab asks for before any more tools are built:
start the server, run this, and confirm a real response comes back over the
wire. It now calls each tool as it is added, so CI proves every one of them is
registered and callable. The one-tool output is kept in data/report/.

Calling flag_for_human_review writes one real flag to the review queue on every
run (review-queue/review_queue.jsonl by default, which git ignores). Its text
says it came from this script, so a reviewer can tell it is not a real request.

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

# A role in data/policies.json, and one that deliberately has no policy.
KNOWN_ROLE = "standard"
UNKNOWN_ROLE = "contractor"

# An item in the catalogue, for the eligibility check.
KNOWN_ITEM = "laptop"

# The text of the flag this check writes, saying plainly where it came from.
CHECK_REQUEST = "Connection check from scripts/check_connection.py: not a real request."
CHECK_REASON = "Confirms flag_for_human_review is callable; no action needed."


def print_result(result: CallToolResult) -> None:
    """Print one tool result: the error flag, the data, and the text."""
    print(f"  is_error:           {result.is_error}")
    print(f"  structured_content: {result.structured_content}")

    for block in result.content:
        # A result can carry several blocks, and only text blocks have .text.
        if hasattr(block, "text"):
            print(f"  text:               {block.text}")


async def check(url: str) -> None:
    """Connect to the server, list its tools, then call each tool twice.

    Once with an input that exists and once with one that does not, so a
    single run shows both the normal path and the error path for every tool.
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
        print()

        # The second tool, both paths again. An unknown role is a question the
        # tool cannot answer, so it arrives the same way an unknown id does.
        print(f"Calling get_policy_limits({KNOWN_ROLE!r}) - a role with a policy:")
        limits = await client.call_tool("get_policy_limits", {"role": KNOWN_ROLE})
        print_result(limits)
        print()

        print(f"Calling get_policy_limits({UNKNOWN_ROLE!r}) - no such role:")
        no_policy = await client.call_tool("get_policy_limits", {"role": UNKNOWN_ROLE})
        print_result(no_policy)
        print()

        # The third tool. A known employee gets both verdicts back as a normal
        # result, whatever they say; only the unknown id sets the error flag.
        print(
            f"Calling check_request_eligibility({KNOWN_EMPLOYEE_ID!r}, {KNOWN_ITEM!r})"
            " - a known employee:"
        )
        eligible = await client.call_tool(
            "check_request_eligibility",
            {"employee_id": KNOWN_EMPLOYEE_ID, "item": KNOWN_ITEM},
        )
        print_result(eligible)
        print()

        print(
            f"Calling check_request_eligibility({UNKNOWN_EMPLOYEE_ID!r}, {KNOWN_ITEM!r})"
            " - no such employee:"
        )
        not_checked = await client.call_tool(
            "check_request_eligibility",
            {"employee_id": UNKNOWN_EMPLOYEE_ID, "item": KNOWN_ITEM},
        )
        print_result(not_checked)
        print()

        # The fourth tool, the only one that changes something. The known
        # employee's call writes one real flag and returns it as queued. The
        # unknown id is refused before anything is written, so it adds nothing.
        print(f"Calling flag_for_human_review({KNOWN_EMPLOYEE_ID!r}, ...) - a known employee:")
        flagged = await client.call_tool(
            "flag_for_human_review",
            {"employee_id": KNOWN_EMPLOYEE_ID, "request": CHECK_REQUEST, "reason": CHECK_REASON},
        )
        print_result(flagged)
        print()

        print(f"Calling flag_for_human_review({UNKNOWN_EMPLOYEE_ID!r}, ...) - no such employee:")
        not_flagged = await client.call_tool(
            "flag_for_human_review",
            {"employee_id": UNKNOWN_EMPLOYEE_ID, "request": CHECK_REQUEST, "reason": CHECK_REASON},
        )
        print_result(not_flagged)


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
