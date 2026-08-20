from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, call

import pytest

from events_aggregator.domain.errors import PaginationLoopError
from events_aggregator.provider.client import ProviderEventsPage
from events_aggregator.provider.paginator import EventsPageSource, EventsPaginator


async def test_paginator_lazily_iterates_multiple_pages(event_factory) -> None:
    changed_at = datetime(2026, 8, 19, tzinfo=timezone.utc)
    first = event_factory("event-1")
    second = event_factory("event-2")
    third = event_factory("event-3")
    provider = AsyncMock(spec=EventsPageSource)
    provider.events.side_effect = [
        ProviderEventsPage(items=[first, second], next_cursor="cursor-2"),
        ProviderEventsPage(items=[third], next_cursor=None),
    ]
    paginator = EventsPaginator(provider, changed_at)

    iterator = paginator.__aiter__()
    provider.events.assert_not_awaited()
    assert await iterator.__anext__() == first
    provider.events.assert_awaited_once_with(changed_at, None)
    assert await iterator.__anext__() == second
    assert provider.events.await_count == 1
    assert await iterator.__anext__() == third
    with pytest.raises(StopAsyncIteration):
        await iterator.__anext__()

    assert provider.events.await_args_list == [
        call(changed_at, None),
        call(changed_at, "cursor-2"),
    ]


async def test_paginator_detects_repeated_cursor() -> None:
    changed_at = datetime(2026, 8, 19, tzinfo=timezone.utc)
    provider = AsyncMock(spec=EventsPageSource)
    provider.events.side_effect = [
        ProviderEventsPage(items=[], next_cursor="repeat"),
        ProviderEventsPage(items=[], next_cursor="repeat"),
    ]

    with pytest.raises(PaginationLoopError, match="repeated"):
        _ = [event async for event in EventsPaginator(provider, changed_at)]

    assert provider.events.await_args_list == [
        call(changed_at, None),
        call(changed_at, "repeat"),
    ]
