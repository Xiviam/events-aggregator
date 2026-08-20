from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from events_aggregator.application.cache import AsyncTTLCache
from events_aggregator.application.seats import GetAvailableSeatsUseCase
from events_aggregator.domain.errors import EventNotFoundError
from events_aggregator.domain.protocols import EventRepository, EventsProvider


async def test_seats_are_cached_for_thirty_seconds(event_factory) -> None:
    monotonic_time = [0.0]
    cache = AsyncTTLCache[str, tuple[str, ...]](
        ttl_seconds=30,
        clock=lambda: monotonic_time[0],
    )
    events = AsyncMock(spec=EventRepository)
    events.get.return_value = event_factory()
    provider = AsyncMock(spec=EventsProvider)
    provider.available_seats.side_effect = [["A1", "A2"], ["B1"]]
    use_case = GetAvailableSeatsUseCase(events, provider, cache)

    assert await use_case.execute("event-1") == ["A1", "A2"]
    monotonic_time[0] = 29.999
    assert await use_case.execute("event-1") == ["A1", "A2"]
    monotonic_time[0] = 30.0
    assert await use_case.execute("event-1") == ["B1"]

    assert provider.available_seats.await_count == 2


async def test_seats_do_not_call_provider_for_unknown_event() -> None:
    events = AsyncMock(spec=EventRepository)
    events.get.return_value = None
    provider = AsyncMock(spec=EventsProvider)
    cache = AsyncTTLCache[str, tuple[str, ...]](ttl_seconds=30)

    with pytest.raises(EventNotFoundError):
        await GetAvailableSeatsUseCase(events, provider, cache).execute("missing")

    provider.available_seats.assert_not_awaited()


async def test_cache_prevents_concurrent_loader_stampede() -> None:
    cache = AsyncTTLCache[str, tuple[str, ...]](ttl_seconds=30)
    release_loader = asyncio.Event()
    loader_started = asyncio.Event()
    call_count = 0

    async def loader() -> tuple[str, ...]:
        nonlocal call_count
        call_count += 1
        loader_started.set()
        await release_loader.wait()
        return ("A1",)

    tasks = [asyncio.create_task(cache.get_or_load("event-1", loader)) for _ in range(5)]
    await loader_started.wait()
    await asyncio.sleep(0)
    assert call_count == 1
    release_loader.set()

    assert await asyncio.gather(*tasks) == [("A1",)] * 5
    assert call_count == 1


async def test_cache_does_not_store_loader_errors() -> None:
    cache = AsyncTTLCache[str, tuple[str, ...]](ttl_seconds=30)
    loader = AsyncMock(side_effect=[RuntimeError("provider down"), ("A1",)])

    with pytest.raises(RuntimeError, match="provider down"):
        await cache.get_or_load("event-1", loader)

    assert await cache.get_or_load("event-1", loader) == ("A1",)
    assert loader.await_count == 2
