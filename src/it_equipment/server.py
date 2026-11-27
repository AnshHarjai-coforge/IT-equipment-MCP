"""The MCP server: the four tools, and the edge between the domain code and the protocol.

The business logic stays in models.py, repository.py, eligibility.py and
review_queue.py, which know nothing about MCP. This module is the edge: it converts what those
modules produce into what the protocol needs, and converts their errors into
the error the protocol understands. The only other modules that import mcp
are on the client side: agent/mcp_bridge.py and evals/cli.py.

Two conversions happen here, and nowhere else:

    - The clock is read (date.today(), datetime.now()) and review flags are
      given random ids (uuid4()), only inside the tool functions, because a
      tool call happens at a particular moment. Nothing beneath them looks at
      the clock or makes an id; each is passed down as an argument, so the same
      inputs always give the same answer.
    - EmployeeNotFoundError and RoleNotFoundError become ToolError, the SDK's
      way of telling the caller that a tool could not do its job.
"""

from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from it_equipment.config import load_settings
from it_equipment.eligibility import decide_eligibility
from it_equipment.repository import (
    EmployeeNotFoundError,
    EmployeeRepository,
    PolicyRepository,
    RoleNotFoundError,
    load_employees_from_json,
    load_policies_from_json,
)
from it_equipment.review_queue import ReviewFlag, ReviewQueue


def employee_info(repository: EmployeeRepository, employee_id: str, as_of: date) -> dict[str, Any]:
    """Look up an employee and return the record as a JSON-ready dictionary.

    This is a plain function with no decorator on it, so a test can call it
    directly rather than going through the protocol. A failure then points at
    this logic instead of at the plumbing.

    An unknown employee id is raised as ToolError rather than returned as a
    "not found" value. ToolError is the only exception whose message the SDK
    passes on to the caller: anything else is replaced with a bare "Error
    executing tool get_employee_info", which would leave the agent unable to
    tell a missing employee from a bug. The call itself still succeeds at the
    protocol level, with an error flag set, so the agent can also tell both of
    those apart from the connection having failed.
    """
    try:
        employee = repository.get_employee(employee_id)
    except EmployeeNotFoundError as error:
        raise ToolError(str(error)) from error

    return employee.to_dict(as_of=as_of)


def policy_limits(policies: PolicyRepository, role: str) -> dict[str, Any]:
    """Look up a role's policy and return it as a JSON-ready dictionary.

    A plain function for the same reason as employee_info: a test calls it
    directly, without the protocol in the way.

    An unknown role is raised as ToolError, for the same reason as an unknown
    employee id: the tool cannot answer the question, and ToolError is the only
    exception whose message reaches the caller. That message lists the known
    roles, so the agent can see it passed something other than what
    get_employee_info reported.

    No date is needed: a policy says how often items are replaced, not how old
    anyone's items are.
    """
    try:
        policy = policies.get_policy(role)
    except RoleNotFoundError as error:
        raise ToolError(str(error)) from error

    return policy.to_dict()


def request_eligibility(
    employees: EmployeeRepository,
    policies: PolicyRepository,
    employee_id: str,
    item: str,
    as_of: date,
) -> dict[str, Any]:
    """Decide whether an employee may have an item, and return the decision as a dictionary.

    A plain function for the same reason as employee_info: a test calls it
    directly, without the protocol in the way.

    Only a question the tool cannot answer raises ToolError: an unknown
    employee id, or an employee whose role has no policy. Being outside policy
    is an answer, not a failure, so a "denied" or "needs_review" verdict
    returns normally like any other.
    """
    try:
        employee = employees.get_employee(employee_id)
    except EmployeeNotFoundError as error:
        raise ToolError(str(error)) from error

    # The role comes from the employee's record, never from the caller, so a
    # request cannot be checked against some other role's limits.
    try:
        policy = policies.get_policy(employee.role)
    except RoleNotFoundError as error:
        raise ToolError(str(error)) from error

    # "Monitor " and "monitor" are the same request. Nothing further is
    # guessed: a word the catalogue lacks goes to a person under rule 1.
    tidy_item = item.strip().lower()

    decision = decide_eligibility(employee, policy, policies.catalogue(), tidy_item, as_of)
    return decision.to_dict()


def human_review(
    employees: EmployeeRepository,
    queue: ReviewQueue,
    employee_id: str,
    request: str,
    reason: str,
    flag_id: str,
    flagged_at: datetime,
) -> dict[str, Any]:
    """Record a request for a person to decide, and return the flag as a dictionary.

    A plain function for the same reason as employee_info: a test calls it
    directly, without the protocol in the way. The id and the time are passed
    in rather than made here, so a test can assert fixed values.

    Each check raises ToolError, because each is a flag the tool cannot record:
    there is no such employee, or a reviewer would be handed nothing to act
    on. Every check comes before the write, so a refused flag records nothing.
    """
    # The record itself is not needed, only the lookup: it is how an unknown id
    # is caught before anything is written. A flag for an employee who does not
    # exist would leave a reviewer nobody to answer.
    try:
        employees.get_employee(employee_id)
    except EmployeeNotFoundError as error:
        raise ToolError(str(error)) from error

    # Whitespace alone counts as blank, since "   " gives a reviewer no more to
    # go on than "". The text is still stored exactly as it was passed.
    if request.strip() == "":
        raise ToolError(
            "The request is blank. Pass the employee's request in their own words, "
            "so a reviewer knows what was asked."
        )

    if reason.strip() == "":
        raise ToolError(
            "The reason is blank. Say why this needs a person, so a reviewer knows what to check."
        )

    flag = ReviewFlag(
        flag_id=flag_id,
        employee_id=employee_id,
        request=request,
        reason=reason,
        flagged_at=flagged_at,
    )
    queue.add(flag)

    # "queued" goes in the reply only, not the file. Being in the file is what
    # queued means, and once a person has dealt with the flag a stored "queued"
    # would be wrong for good, in a file that is only ever appended to.
    result = flag.to_dict()
    result["status"] = "queued"
    return result


def build_server(
    employees: EmployeeRepository,
    policies: PolicyRepository,
    review_queue: ReviewQueue,
) -> MCPServer:
    """Build the MCP server and register its tools.

    The repositories and the review queue are handed in rather than made here,
    so a caller decides where the data comes from and where flags go, and there
    is no module-level state. The entry point below is what does the loading.
    """
    mcp = MCPServer("it-equipment")

    # The return type is dict[str, Any] rather than a bare dict on purpose. A
    # bare dict produces no output schema, and the result then reaches the
    # client only as JSON text. Naming the key and value types makes the SDK
    # publish a schema and hand the caller the dictionary itself.
    # The docstring below is not a note for us. It is the description the model
    # reads when deciding whether to call this tool, so it is written for that
    # reader: a one-line summary, what failure means, then each argument with an
    # example of its format. These comments are invisible to the model, as is
    # the body of the function; the name, the docstring and the type hints are
    # the whole interface it gets.
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_employee_info(employee_id: str) -> dict[str, Any]:
        """Get an employee's role, tenure, and current equipment with each item's age.

        Tenure (tenure_years) and each item's age (age_years) are whole years,
        counted up to today.

        Fails if no employee has that id, so the id should be verified, not
        guessed.

        Args:
            employee_id: The employee's id (e.g. E001)
        """
        # The tool functions are the only places that read the clock or make a
        # random id. Everything below this line receives the date as an argument.
        return employee_info(employees, employee_id, as_of=date.today())

    # The same conventions as above: read-only, dict[str, Any] so a schema is
    # published, and a docstring written for the model. It describes the limits
    # without inviting the model to apply them, because deciding a request is
    # the eligibility check's job, not the model's.
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def get_policy_limits(role: str) -> dict[str, Any]:
        """Get what a role is eligible for: each item, how many, and how often replaced.

        For each item the role may hold, gives the most it may hold at once
        (max_quantity) and after how many whole years one is replaced
        (refresh_years).

        Fails if no policy exists for that role; the error lists the roles
        that have one.

        Args:
            role: The role exactly as get_employee_info reports it (e.g. standard)
        """
        return policy_limits(policies, role)

    # Read-only like the other two: it decides, but records nothing. The
    # docstring tells the model that the verdict is the decision, so it relays
    # one rather than reasoning its way to its own.
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    def check_request_eligibility(employee_id: str, item: str) -> dict[str, Any]:
        """Decide whether an employee's request for an item is within policy.

        Always gives two verdicts. "additional" answers a request for one
        more, kept alongside what the employee already holds. "replacement"
        answers a request for a new one in place of their oldest, which goes
        back. Use the verdict that matches what the employee asked for.

        Each verdict is "approved", "denied" or "needs_review", with a reason
        to relay. The verdict is the decision: do not recalculate it from the
        other fields. "needs_review" means a person must decide. When a
        replacement is denied only because the item is too new,
        next_eligible_on gives the date it becomes due; otherwise it is null,
        and no date should be offered.

        Fails if no employee has that id, or if the employee's role has no
        policy. A denial is not a failure.

        Args:
            employee_id: The employee's id (e.g. E001)
            item: The item in the policy's own words (e.g. laptop, monitor,
                docking station), not a brand or a description
        """
        return request_eligibility(employees, policies, employee_id, item, as_of=date.today())

    # The one tool that changes something: each call adds a flag to the queue.
    # All three hints are written out, because the SDK treats a missing
    # destructiveHint as true. Not destructive, because a flag is only ever
    # added and nothing already recorded is changed or removed. Not
    # idempotent, because calling it twice with the same arguments records two
    # flags, not one.
    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
        )
    )
    def flag_for_human_review(employee_id: str, request: str, reason: str) -> dict[str, Any]:
        """Send a request to a person for review, and record why.

        Use this when check_request_eligibility returns "needs_review", or when
        the request is ambiguous: it claims something the records cannot confirm
        (damage, loss, a medical need), it is unclear which item or kind of
        request is meant, or it asks for several things at once. Each call records
        a new flag, so call it once per request. The result gives the flag_id.

        Fails if no employee has that id, or if the request or reason is blank.
        Nothing is recorded when it fails.

        Args:
            employee_id: The employee's id (e.g. E001)
            request: The employee's request in their own words (e.g. I dropped
                my laptop and cracked the screen)
            reason: Why a person must decide, in one sentence (e.g. The damage
                cannot be confirmed from the records)
        """
        # The id and the time are made here, as date.today() is in the tools
        # above, so the plain function receives them and a test can pass fixed
        # values. The time is taken in UTC so flags from anywhere sort the same.
        return human_review(
            employees,
            review_queue,
            employee_id,
            request,
            reason,
            flag_id=str(uuid4()),
            flagged_at=datetime.now(timezone.utc),
        )

    return mcp


if __name__ == "__main__":
    # The one place that wires everything together: read the settings, load the
    # data, then start serving. Guarded because the tests and the mcp
    # command-line tools import this module, and importing it must not start a
    # server.
    settings = load_settings()
    employees = load_employees_from_json(settings.employees_file)
    policies = load_policies_from_json(settings.policies_file)
    review_queue = ReviewQueue(settings.review_queue_file)

    build_server(employees, policies, review_queue).run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        # The same path the client builds into its URL. Both sides read it from
        # one setting, so changing it cannot leave them pointing at different
        # endpoints.
        streamable_http_path=settings.path,
    )
