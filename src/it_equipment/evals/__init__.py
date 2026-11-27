"""The eval harness: the demo requests as cases, graded against what a correct run looks like.

The cases are in data/eval_cases.json. Two things use them: a CI test that
checks the server's answers still support every case, with no model, and a
paid runner, python -m it_equipment.evals, that runs the agent on every case
with the real model and prints a scorecard.
"""
