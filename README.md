# IT-equipment-MCP

An internal IT equipment request handler, built as two pieces:

- an **MCP server** exposing a mock employee, policy and equipment system as tools, and
- an **agent** that connects to that server as a client, investigates a natural-language
  request using those tools, and either answers it or escalates it for human review.

The full requirements are in [`data/Lab/mcp_equipment_request_lab_formatted.md`](data/Lab/mcp_equipment_request_lab_formatted.md).

## Status

The first tool, `get_employee_info`, is served over MCP and confirmed working end to end:
the server registers it, and a client script connects and calls it. The remaining three
tools and the agent are still to come.

## Requirements

Python 3.12.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

These are the same three checks CI runs, in the same order:

```bash
ruff check .            # lint
ruff format --check .   # formatting
pytest                  # tests
```

To run a single test:

```bash
pytest tests/test_repository.py::test_unknown_employee_id_raises -v
```

## Looking up an employee

```bash
python -c "
from datetime import date
from it_equipment.repository import load_employees_from_json
repo = load_employees_from_json('data/employees.json')
print(repo.get_employee('E001').to_dict(as_of=date.today()))
"
```

## Running the MCP server

The server listens on a port, so it runs in one terminal and clients connect to it from
another. Start it:

```bash
python -m it_equipment.server
```

Then, in a second terminal, confirm the connection works. This lists the tools the server
registered and calls one with both a known and an unknown employee id:

```bash
python scripts/check_connection.py
```

## Configuration

Settings live in [`config.toml`](config.toml). Every one of them has a default in
`src/it_equipment/config.py`, so the program runs without any configuration at all.

Each setting can also be overridden by an environment variable, which is how a container
changes one without the image being rebuilt:

| Variable | Setting | Default |
| --- | --- | --- |
| `MCP_HOST` | address the server listens on | `127.0.0.1` |
| `MCP_PORT` | port the server listens on | `8000` |
| `MCP_PATH` | path the MCP endpoint lives at | `/mcp` |
| `MCP_EMPLOYEES_FILE` | the employee records to load | `data/employees.json` |

The order is defaults, then `config.toml`, then the environment, each overriding the one
before. Both the server and the client script read the same settings, so they cannot end up
pointing at different addresses:

```bash
MCP_PORT=9000 python -m it_equipment.server        # terminal 1
MCP_PORT=9000 python scripts/check_connection.py   # terminal 2
```

Note that policy rules are **not** settings. They are the thing the system exists to apply,
so they belong in a data file under `data/` with tests asserting on them.

## Layout

```
src/it_equipment/models.py        Employee and EquipmentItem data types
src/it_equipment/repository.py    employee lookups: get_employee
src/it_equipment/config.py        Settings, and the loader that layers them
src/it_equipment/server.py        the MCP server and its tools
scripts/check_connection.py       connects as a client and calls a tool
config.toml                       application settings
tests/                            unit tests, run against the plain functions
data/employees.json               mock employee records
data/Lab/                         the lab brief
.github/workflows/ci.yml          the CI pipeline
```

Business logic lives in plain functions and classes with no MCP imports: `server.py` is the
only module that imports `mcp`, and it is a thin wrapper over those plain functions, so the
logic stays directly testable.
