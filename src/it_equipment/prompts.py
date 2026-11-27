"""The instructions the agent gives the model.

Kept apart from the code that sends them, so the wording can be read, reviewed
and changed on its own. A change here changes what the model is told, and
nothing else.
"""

# One sentence for now, because all the agent does so far is make a single
# tool call. The full instructions come with the ReAct loop.
SYSTEM_PROMPT = (
    "You handle internal IT equipment requests. "
    "Use the tools to look up the facts before you answer."
)
