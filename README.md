# IT-equipment-MCP

An internal IT equipment request handler, built as two pieces:

- an **MCP server** exposing a mock employee, policy and equipment system as tools, and
- an **agent** that connects to that server as a client, investigates a natural-language
  request using those tools, and either answers it or escalates it for human review.

The lab brief is [`data/Lab/mcp_equipment_request_lab_formatted.md`](data/Lab/mcp_equipment_request_lab_formatted.md).
The policy rules, and what makes a request ambiguous, are defined in
[`docs/requirements.md`](docs/requirements.md).

## Status

Three of the four tools are served over MCP and confirmed working end to end:

- `get_employee_info`: an employee's role, tenure, and equipment with each item's age
- `get_policy_limits`: what a role may hold, and after how many years each item is replaced
- `check_request_eligibility`: whether a request for an item is within policy, answered both
  as an additional item and as a replacement, each with a verdict and a reason

`flag_for_human_review` and the agent are still to come.

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
registered and calls each one twice, with an input that exists and one that doesn't:

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
| `MCP_POLICIES_FILE` | the role policies to load | `data/policies.json` |

The order is defaults, then `config.toml`, then the environment, each overriding the one
before. Both the server and the client script read the same settings, so they cannot end up
pointing at different addresses:

```bash
MCP_PORT=9000 python -m it_equipment.server        # terminal 1
MCP_PORT=9000 python scripts/check_connection.py   # terminal 2
```

Note that policy rules are **not** settings. They are the thing the system exists to apply,
so they live in `data/policies.json`, with a test asserting the whole table. Only the file's
location is a setting.

## Layout

```
src/it_equipment/models.py        data types: employees, equipment, role policies
src/it_equipment/repository.py    employee and policy lookups, and the item catalogue
src/it_equipment/eligibility.py   the eligibility rules: every policy decision is made here
src/it_equipment/config.py        Settings, and the loader that layers them
src/it_equipment/server.py        the MCP server and its tools
scripts/check_connection.py       connects as a client and calls each tool
config.toml                       application settings
tests/                            unit tests, run against the plain functions
docs/requirements.md              requirements and policy rules (deliverable 1)
data/employees.json               mock employee records
data/policies.json                mock policy rules, one record per role
data/report/                      captured evidence for the lab report
data/Lab/                         the lab brief
.github/workflows/ci.yml          the CI pipeline
```

Business logic lives in plain functions and classes with no MCP imports: `server.py` is the
only module that imports `mcp`, and it is a thin wrapper over those plain functions, so the
logic stays directly testable.
