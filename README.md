# IT-equipment-MCP

An internal IT equipment request handler, built as two pieces:

- an **MCP server** exposing a mock employee, policy and equipment system as tools, and
- an **agent** that connects to that server as a client, investigates a natural-language
  request using those tools, and either answers it or escalates it for human review.

The lab brief is [`data/Lab/mcp_equipment_request_lab_formatted.md`](data/Lab/mcp_equipment_request_lab_formatted.md).
The policy rules, and what makes a request ambiguous, are defined in
[`docs/requirements.md`](docs/requirements.md).

## Status

All four tools are served over MCP and confirmed working end to end:

- `get_employee_info`: an employee's role, tenure, and equipment with each item's age
- `get_policy_limits`: what a role may hold, and after how many years each item is replaced
- `check_request_eligibility`: whether a request for an item is within policy, answered both
  as an additional item and as a replacement, each with a verdict and a reason
- `flag_for_human_review`: sends a request to a person, by appending a flag with the reason to
  the review queue

The agent connects to the server as an MCP client and runs an explicit ReAct loop over those
tools for the request it is given, printing every Thought, Action and Observation, until the
model writes its draft decision. Reflection on that draft is still to come.

The eight demo requests are also eval cases: CI checks that the server still gives each one the
answers it needs, and a paid runner grades the agent on all eight at once.

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

Each run writes one real flag to the review queue, `review-queue/review_queue.jsonl`, whose
text says it came from the connection check. The folder is created on the first flag and is
git-ignored, because flags are written while the server runs rather than authored as data.

## Running the agent

The agent calls Claude Opus 5 on Microsoft Foundry. It needs a Foundry key, the resource
name and the deployment name, which live in a `.env` file that git ignores. Create it once
from the template and fill it in:

```bash
cp .env.example .env
```

| Variable | What it is |
| --- | --- |
| `ANTHROPIC_FOUNDRY_API_KEY` | the Foundry key; the `anthropic` SDK reads it itself |
| `ANTHROPIC_FOUNDRY_RESOURCE` | the Foundry resource name; the SDK reads it itself |
| `ANTHROPIC_MODEL` | the Foundry deployment name, which defaults to `claude-opus-5` |

The agent loads `.env` by itself when it starts. **Never `source .env` into a terminal:**
Claude Code also reads `ANTHROPIC_MODEL`, and would take the deployment name as its own model.
A variable already set in the environment wins over `.env`.

With the server running in one terminal, run the agent in a second. Give it the id of the
employee who sent the request, then their words in quotes:

```bash
python -m it_equipment.server   # terminal 1
python -m it_equipment.agent E001 "My laptop is 4 years old and slow, can I get a replacement?"   # terminal 2
```

The id is passed separately because it comes from whoever sent the request, never from the
text. `python -m it_equipment.agent --help` shows the usage.

The agent runs a ReAct loop. Each pass is one call to the model, which either asks for tools
or writes its draft decision. Every tool call carries the model's reason for it, so everything
is printed in full as it happens:

- `User query`: who sent the request, and their words exactly as sent
- `Step 1: ReAct loop`: each Thought, Action and Observation, numbered across the whole loop;
  the Observation is the tool's result exactly as the model is given it
- `Draft after the ReAct loop`: the decision (approved, denied, escalated or not processed),
  the item, which verdict it relays, the message to the employee, the reason, and the flag id

If the loop ends without a draft (the model refuses, is cut off, or reaches the limit of
`max_steps` calls), the agent says why in one line, and Python sends the request to a person
with `flag_for_human_review`, printing the flag's id. Each call to the model is a paid call, so
the tests replace the model with a scripted fake and never make one.

If the server isn't running, or if Foundry refuses the call, the agent says so in a line or two
and exits with status 1. A missing argument or a blank request prints the usage and exits with
status 2.

## Evaluating the agent

[`data/eval_cases.json`](data/eval_cases.json) holds the eight demo requests as eval cases. Each
case has the sender and their words, and what a correct run looks like:

- `expected`: the draft's decision, item and answered, and whether a flag is recorded
- `verdicts`: the two verdicts `check_request_eligibility` gives, as of the tests' fixed date
  (`null` when no employee has the id)
- `required_calls`: tool calls the run must include, listing only the arguments that matter
- `forbidden_calls`: tool calls the run must not include; one with no arguments forbids the
  tool outright

The cases are used twice.

**In CI, with no model.** `tests/evals/test_cases_against_server.py` makes each case's required
calls with the server's plain functions and checks the answers: for example, case 1's
`check_request_eligibility("E001", "laptop")` must still give the replacement `approved`. A
change to the employees or the policies that would quietly break a demo answer fails `pytest`.

**With the real model, paid.** The runner runs the agent on every case and grades each run:

```bash
python -m it_equipment.evals              # every case once
python -m it_equipment.evals --repeat 3   # every case three times, to see how steady it is
```

It needs the same `.env` as the agent, and loads it the same way. No server needs to be running:
it builds one inside its own process, from the same data files, with the review queue in a
temporary folder that is deleted at the end, so the real `review-queue/` is never touched.

For each run it prints a heading naming the case, the agent's trace exactly as
`python -m it_equipment.agent` prints it, and a `Result`: passed or failed, the problems, and
how many calls to the model the run made. What is graded is the final answer, the one the
employee gets after reflection and the Python check. A run passes when:

- the final answer's decision, item and answered are the case's, exactly; a run whose ReAct
  loop ended without a draft fails, whatever Python did next
- every required call was made (other calls, in any order, are allowed)
- no forbidden call was made
- one flag was recorded when the case expects one, none otherwise, and any flag id in the final
  answer is one the run received; a flag Python made counts as the run's flag

The message text is not graded. At the end a scorecard gives one row per case and repeats every
failed run's problems. The runner exits with status 1 if any run failed. Each case takes about
three to five calls to the model, reflection's included, so one pass over the ten is roughly 35
paid calls.

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
| `MCP_REVIEW_QUEUE_FILE` | where review flags are appended | `review-queue/review_queue.jsonl` |
| `ANTHROPIC_MODEL` | the Foundry deployment the agent calls | `claude-opus-5` |
| `AGENT_MAX_STEPS` | the most model calls for one request | `10` |
| `AGENT_MAX_TOKENS` | the most the model may write in one reply, thinking included | `16000` |

The Foundry key and resource name are not settings: the `anthropic` SDK reads them from the
environment by itself, so they never appear in the `Settings` object.

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
src/it_equipment/review_queue.py  review flags, and the queue file they are appended to
src/it_equipment/config.py        Settings, and the loader that layers them
src/it_equipment/server.py        the MCP server and its tools
src/it_equipment/agent/           the agent, one job per module:
    __main__.py                   what "python -m it_equipment.agent" runs: loads .env, then main()
    cli.py                        the command line: reads the request, opens both clients
    request.py                    a request: the sender's id and their words, as one message
    prompts.py                    what the agent tells the model
    handler.py                    one request start to finish; Python escalates if no draft
    react_loop.py                 the ReAct loop: model calls and tool calls until a draft
    draft.py                      the draft decision, its schema, and reading it back
    mcp_bridge.py                 MCP tools into Claude tools, and tool results into text
    trace.py                      the trace's steps, and how everything is printed
src/it_equipment/evals/           the eval harness, one job per module:
    __main__.py                   what "python -m it_equipment.evals" runs: loads .env, then main()
    cli.py                        the runner: builds the server in-process, runs every case
    cases.py                      the eval cases, and reading them from the JSON file
    grading.py                    grading one run against its case
    model_calls.py                counts the agent's calls to the model
    scorecard.py                  each run's result, and the scorecard
scripts/check_connection.py       connects as a client and calls each tool
config.toml                       application settings
.env.example                      the template for .env, which holds the Foundry key
tests/                            unit tests, run against the plain functions
tests/agent/                      the agent's tests, one file per module
tests/evals/                      the eval harness's tests, and the CI check of every case
docs/requirements.md              requirements and policy rules (deliverable 1)
data/employees.json               mock employee records
data/policies.json                mock policy rules, one record per role
data/eval_cases.json              the demo requests as eval cases
data/report/                      captured evidence for the lab report
data/Lab/                         the lab brief
review-queue/                     review flags written by the server (git-ignored)
.github/workflows/ci.yml          the CI pipeline
```

Business logic lives in plain functions and classes with no MCP imports: `server.py` is the
only module on the server side that imports `mcp`, and it is a thin wrapper over those plain
functions, so the logic stays directly testable. On the agent side, `agent/mcp_bridge.py` is
the only module that imports `mcp`. The eval runner, `evals/cli.py`, imports it too, to build
the server inside its own process.
