"""Tests for SSE event replay semantics."""

from __future__ import annotations

import asyncio

import pytest

from api.events import EventBus, EventType, SSEEvent


@pytest.mark.asyncio
async def test_late_subscriber_replays_history_without_queue_duplicate():
    bus = EventBus()
    task_id = "task-1"
    bus.create_task(task_id)

    await bus.publish(
        task_id,
        SSEEvent(event_type=EventType.LOG, data={"message": "first"}),
    )

    received: list[SSEEvent] = []

    async def collect_events() -> None:
        async for event in bus.subscribe(task_id):
            received.append(event)

    consumer = asyncio.create_task(collect_events())
    await asyncio.sleep(0)
    await bus.close(task_id)
    await consumer

    assert [event.data["message"] for event in received] == ["first"]
