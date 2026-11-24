# Deliverable evidence

Terminal output captured for the report, in the order the lab brief lists its deliverables.

## Captured so far

| File | Deliverable |
| --- | --- |
| `step3-terminal1-server.txt` | #2 — the minimal server starting and serving |
| `step3-terminal2-client.txt` | #2 — the client connecting, listing one tool, and calling it |

These two are captured **now, and cannot be recaptured later.** Deliverable #2 asks for proof
that a *one-tool* server and client connection worked *before* the full build. Once the other
three tools are registered, `tools/list` will report four tools and the output will no longer
evidence that milestone.

Worth noting in the report: terminal 1 shows the server logging the failed call for `E999`,
while terminal 2 shows the same failure arriving at the client as `is_error: True` with a
readable message. Together they show the two halves of the error design.

## Still to capture, deliberately left until later

Everything below will change as the remaining tools and the agent are built, so capturing it
now would only mean capturing it twice.

| Deliverable | Capture when |
| --- | --- |
| #1 requirements doc and policy rules | once the policy rules are written |
| #3 server code, all four tools | once all four exist |
| #4 unit tests and their passing output | once there are tests per tool |
| #5 agent code with its MCP client connection | once the agent exists |
| #6 ReAct traces for the 4 test requests | once the ReAct loop runs |
| #7 final decision and escalation reason per request | with the traces |
| #8 the reflection step catching or confirming a draft | once reflection is added |
| #9 a passing pipeline run | from the final CI run, so it covers everything |
