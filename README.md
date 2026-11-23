# IT-equipment-MCP

An internal IT equipment request handler, built as two pieces:

- an **MCP server** exposing a mock employee, policy and equipment system as tools, and
- an **agent** that connects to that server as a client, investigates a natural-language
  request using those tools, and either answers it or escalates it for human review.

The full requirements are in [`data/Lab/mcp_equipment_request_lab_formatted.md`](data/Lab/mcp_equipment_request_lab_formatted.md).

## Status

Project skeleton and CI pipeline only. No tools are implemented yet.

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

To run a single test once tests exist:

```bash
pytest tests/test_repository.py::test_name -v
```

## Layout

```
src/it_equipment/    the package: MCP server tools and the agent
tests/               unit tests, run directly against the plain functions
data/                mock data and the lab brief
.github/workflows/   the CI pipeline
```
