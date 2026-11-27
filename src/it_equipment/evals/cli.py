"""The paid eval runner: the agent on every eval case, with the real model, then a scorecard.

    python -m it_equipment.evals              # every case once
    python -m it_equipment.evals --repeat 3   # every case three times

In plain words:

    1. Read how many times to run each case, and load the cases.
    2. Build the server inside this process, from the same data files the real
       server reads, with its review queue in a temporary folder.
    3. Run each case, its repeats together: print the heading, let the agent
       handle the request exactly as from its own command line, then grade the
       run and print the result.
    4. Print the scorecard, and exit with status 1 if any run failed, as a test
       runner does.

Every run makes real calls to the model, which are paid for, so this never
runs in CI (plan decision 20). The CI half, with no model, is the test
tests/evals/test_cases_against_server.py.

The temporary review queue is deleted at the end, so the real one in
review-queue/ is never touched, and no second terminal is needed. This and
server.py and agent/mcp_bridge.py are the modules that import mcp.
"""

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from anthropic import APIError, AsyncAnthropicFoundry
from mcp import Client

from it_equipment.agent.handler import handle_request
from it_equipment.config import load_settings
from it_equipment.evals.cases import CASES_FILE, EvalCase, load_cases_from_json
from it_equipment.evals.grading import RunGrade, grade_run
from it_equipment.evals.model_calls import CountingModelClient
from it_equipment.evals.scorecard import (
    CaseRun,
    print_case_heading,
    print_run_result,
    print_scorecard,
)
from it_equipment.repository import load_employees_from_json, load_policies_from_json
from it_equipment.review_queue import ReviewQueue
from it_equipment.server import build_server


def runs_from_command_line(arguments: list[str]) -> int:
    """Return how many times to run each case: 1, or the number given with --repeat.

    A number below 1, or not a number, prints the usage line and an error and
    exits with status 2, argparse's own rule for a command used wrongly.
    """
    parser = argparse.ArgumentParser(
        prog="python -m it_equipment.evals",
        description=(
            "Run the agent on every eval case with the real model, and print a scorecard. "
            "Every run makes paid calls to the model."
        ),
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="run each case N times, to see how steady the agent is (default 1)",
    )

    parsed = parser.parse_args(arguments)

    if parsed.repeat < 1:
        parser.error("--repeat must be at least 1")

    return parsed.repeat


async def run_case(
    model_client: AsyncAnthropicFoundry,
    mcp_client: Client,
    model: str,
    max_tokens: int,
    max_steps: int,
    case: EvalCase,
    run_number: int,
) -> CaseRun:
    """Run the agent once on one case, printing its trace as it goes, and return the run graded."""
    # A new counter for every run, so each run's count starts from zero.
    counting_client = CountingModelClient(model_client)

    try:
        result = await handle_request(
            counting_client, mcp_client, model, max_tokens, max_steps, case.request
        )
        grade = grade_run(case, result)
    except APIError as error:
        # Foundry overloaded, a rate limit, a refused key. The run fails with
        # the error shown, and the runner carries on with the next one, so a
        # paid run never loses the results already paid for. The SDK's
        # message is the status and Foundry's reply, never the key.
        grade = RunGrade(
            problems=[f"The model call failed: {type(error).__name__}: {error}"], warnings=[]
        )

    return CaseRun(
        case_id=case.case_id,
        run_number=run_number,
        grade=grade,
        model_calls=counting_client.calls_made(),
    )


async def run_every_case(
    model_client: AsyncAnthropicFoundry,
    mcp_client: Client,
    model: str,
    max_tokens: int,
    max_steps: int,
    cases: list[EvalCase],
    runs: int,
) -> list[CaseRun]:
    """Run each case the given number of times, its runs together, and return every run graded."""
    case_runs = []
    for case in cases:
        for run_number in range(1, runs + 1):
            print_case_heading(case, run_number, runs)
            case_run = await run_case(
                model_client, mcp_client, model, max_tokens, max_steps, case, run_number
            )
            print_run_result(case_run)
            # A blank line between one run's result and whatever comes next.
            print()
            case_runs.append(case_run)

    return case_runs


def every_run_passed(case_runs: list[CaseRun]) -> bool:
    """Return True when no run has a problem."""
    for case_run in case_runs:
        if not case_run.grade.passed():
            return False

    return True


async def main() -> None:
    # The command line is read first, so a mistyped command stops before
    # anything is opened. sys.argv[0] is the program's own name.
    runs = runs_from_command_line(sys.argv[1:])

    settings = load_settings()
    cases = load_cases_from_json(CASES_FILE)
    employees = load_employees_from_json(settings.employees_file)
    policies = load_policies_from_json(settings.policies_file)

    # The model client is opened first, as in the agent. It reads its own key
    # from the environment, and with none it fails right here, before any run,
    # with the SDK's own error: that names the variable and holds no key.
    async with AsyncAnthropicFoundry() as model_client:
        # The folder and everything in it is deleted when the block ends.
        with tempfile.TemporaryDirectory() as folder:
            review_queue = ReviewQueue(Path(folder) / "review_queue.jsonl")
            server = build_server(employees, policies, review_queue)

            # Making the server turns on INFO logging for this whole process
            # (MCPServer calls logging.basicConfig). Left on, the server's
            # "Tool ... failed" lines and an "HTTP Request: POST https://..."
            # line after every model call would print in the middle of the
            # traces, the second naming the Foundry resource. Back to
            # WARNING, the output is what the agent prints on its own.
            logging.getLogger().setLevel(logging.WARNING)

            # Passing the server itself, not an address, connects to it inside
            # this process: the same tools and results as over HTTP.
            async with Client(server) as mcp_client:
                case_runs = await run_every_case(
                    model_client,
                    mcp_client,
                    settings.model,
                    settings.max_tokens,
                    settings.max_steps,
                    cases,
                    runs,
                )

    print_scorecard(cases, runs, case_runs)

    # Like a test runner: a script or a person can tell from the status alone
    # whether every run passed.
    if not every_run_passed(case_runs):
        raise SystemExit(1)
