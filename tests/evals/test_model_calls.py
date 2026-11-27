"""Unit tests for counting the agent's calls to the model.

The real client is a fake that records what it was sent and hands back one
real anthropic Message, so nothing is paid for. The wrapper's create is
asynchronous, so each test runs it with asyncio.run, from the standard library.
"""

import asyncio

import pytest
from anthropic.types import Message, TextBlock, Usage

from it_equipment.evals.model_calls import CountingModelClient

REPLY = Message(
    id="msg_1",
    type="message",
    role="assistant",
    model="claude-opus-5",
    content=[TextBlock(type="text", text="A reply.")],
    stop_reason="end_turn",
    stop_sequence=None,
    usage=Usage(input_tokens=100, output_tokens=50),
)


class RecordingMessages:
    """Stands in for the real client's messages: records each call and returns REPLY."""

    def __init__(self) -> None:
        self.sent = []

    async def create(self, **kwargs) -> Message:
        self.sent.append(kwargs)
        return REPLY


class FailingMessages:
    async def create(self, **kwargs) -> Message:
        raise RuntimeError("The model call failed.")


class FakeModelClient:
    def __init__(self, messages) -> None:
        self.messages = messages


def test_a_new_client_has_made_no_calls():
    counting = CountingModelClient(FakeModelClient(RecordingMessages()))

    assert counting.calls_made() == 0


def test_each_call_is_counted():
    counting = CountingModelClient(FakeModelClient(RecordingMessages()))

    asyncio.run(counting.messages.create(model="claude-opus-5"))
    asyncio.run(counting.messages.create(model="claude-opus-5"))

    assert counting.calls_made() == 2


def test_the_call_is_passed_on_unchanged():
    real = RecordingMessages()
    counting = CountingModelClient(FakeModelClient(real))

    asyncio.run(counting.messages.create(model="claude-opus-5", max_tokens=16000))

    assert real.sent == [{"model": "claude-opus-5", "max_tokens": 16000}]


def test_the_real_reply_is_returned():
    counting = CountingModelClient(FakeModelClient(RecordingMessages()))

    reply = asyncio.run(counting.messages.create(model="claude-opus-5"))

    assert reply is REPLY


def test_a_call_that_fails_still_counts():
    counting = CountingModelClient(FakeModelClient(FailingMessages()))

    with pytest.raises(RuntimeError):
        asyncio.run(counting.messages.create(model="claude-opus-5"))

    assert counting.calls_made() == 1
