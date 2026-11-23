# IT-equipment-MCP

An internal IT equipment request handler, built as two pieces:

- an **MCP server** exposing a mock employee, policy and equipment system as tools, and
- an **agent** that connects to that server as a client, investigates a natural-language
  request using those tools, and either answers it or escalates it for human review.

The full requirements are in [`data/Lab/mcp_equipment_request_lab_formatted.md`](data/Lab/mcp_equipment_request_lab_formatted.md).

## Status

The logic behind the first tool, `get_employee_info`, is implemented and tested as plain
Python. It is not wrapped as an MCP tool yet.

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

## Layout

```
src/it_equipment/models.py        Employee and EquipmentItem data types
src/it_equipment/repository.py    employee lookups: get_employee
tests/                            unit tests, run against the plain functions
data/employees.json               mock employee records
data/Lab/                         the lab brief
.github/workflows/ci.yml          the CI pipeline
```

Business logic lives in plain functions and classes with no MCP imports. The MCP server will
wrap them in thin tool functions, so the logic stays directly testable.
