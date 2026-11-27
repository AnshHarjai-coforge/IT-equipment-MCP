"""Counting the calls the agent makes to the model, without changing the agent.

The runner hands the agent a CountingModelClient in place of the real client.
The agent only ever uses model_client.messages.create, so that is all the
wrapper has: it counts each call and passes it on to the real client unchanged.
The agent's code knows nothing about it, which is the usual way to measure a
dependency without editing the code that uses it. The agent's tests swap in a
fake client in the same way.
"""

from typing import Any

from anthropic.types import Message


class CountedMessages:
    """Stands in for model_client.messages: counts each create call, then makes it for real."""

    def __init__(self, messages: Any) -> None:
        self.messages = messages
        self.count = 0

    async def create(self, **kwargs: Any) -> Message:
        # Counted before the call, so a call that fails still counts: it was
        # made, and the scorecard should show how far the run got.
        self.count = self.count + 1
        return await self.messages.create(**kwargs)


class CountingModelClient:
    """A model client that counts how many calls it passes on to the real one."""

    def __init__(self, model_client: Any) -> None:
        self.messages = CountedMessages(model_client.messages)

    def calls_made(self) -> int:
        """Return how many calls to the model have been made through this client."""
        return self.messages.count
