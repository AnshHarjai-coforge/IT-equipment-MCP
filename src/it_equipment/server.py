"""The MCP server: the only module in the package that imports mcp.

The business logic stays in models.py and repository.py, which know nothing
about MCP. This module is the edge: it converts what those modules produce into
what the protocol needs, and converts their errors into the error the protocol
understands.

Two conversions happen here, and nowhere else:

    - date.today() is read, because a tool call happens on a particular day.
      Nothing beneath this module looks at the clock; the date is passed down as
      an argument so the same inputs always give the same answer.
    - EmployeeNotFoundError becomes ToolError, the SDK's way of telling the
      caller that a tool could not do its job.
"""

from datetime import date
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from it_equipment.config import load_settings
from it_equipment.repository import (
    EmployeeNotFoundError,
    EmployeeRepository,
    load_employees_from_json,
)


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


def build_server(repository: EmployeeRepository) -> MCPServer:
    """Build the MCP server and register its tools.

    The repository is handed in rather than loaded here, so a caller decides
    where the data comes from and there is no module-level state. The entry
    point below is what does the loading.
    """
    mcp = MCPServer("it-equipment")

    # The return type is dict[str, Any] rather than a bare dict on purpose. A
    # bare dict produces no output schema, and the result then reaches the
    # client only as JSON text. Naming the key and value types makes the SDK
    # publish a schema and hand the caller the dictionary itself.
    @mcp.tool()
    def get_employee_info(employee_id: str) -> dict[str, Any]:
        """Look up an employee's role, tenure in whole years, and the
        equipment currently on file for them.

        Takes the employee id, such as "E001". Fails if no employee has that
        id, which means the id should be checked rather than guessed at.
        """
        # The only place in the program that reads the clock. Everything below
        # this line receives the date as an argument.
        return employee_info(repository, employee_id, as_of=date.today())

    return mcp


if __name__ == "__main__":
    # The one place that wires everything together: read the settings, load the
    # data, then start serving. Guarded because the tests and the mcp
    # command-line tools import this module, and importing it must not start a
    # server.
    settings = load_settings()
    repository = load_employees_from_json(settings.employees_file)

    build_server(repository).run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        # The same path the client builds into its URL. Both sides read it from
        # one setting, so changing it cannot leave them pointing at different
        # endpoints.
        streamable_http_path=settings.path,
    )
