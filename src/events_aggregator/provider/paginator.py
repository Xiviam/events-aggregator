from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from events_aggregator.domain.errors import PaginationLoopError
from events_aggregator.domain.models import Event
from events_aggregator.provider.client import ProviderEventsPage


class EventsPageSource(Protocol):
    async def events(
        self,
        changed_at: datetime,
        cursor: str | None = None,
    ) -> ProviderEventsPage: ...


class EventsPaginator:
    """Reusable, lazy asynchronous iterator over all provider event pages."""

    def __init__(self, client: EventsPageSource, changed_at: datetime) -> None:
        self._client = client
        self._changed_at = changed_at

    def __aiter__(self) -> AsyncIterator[Event]:
        return _EventsPaginationIterator(self._client, self._changed_at)


class _EventsPaginationIterator:
    def __init__(self, client: EventsPageSource, changed_at: datetime) -> None:
        self._client = client
        self._changed_at = changed_at
        self._cursor: str | None = None
        self._items: deque[Event] = deque()
        self._requested_cursors: set[str | None] = set()
        self._finished = False

    def __aiter__(self) -> _EventsPaginationIterator:
        return self

    async def __anext__(self) -> Event:
        while not self._items:
            if self._finished:
                raise StopAsyncIteration
            if self._cursor in self._requested_cursors:
                raise PaginationLoopError("Provider returned a repeated pagination cursor")
            self._requested_cursors.add(self._cursor)
            page = await self._client.events(self._changed_at, self._cursor)
            self._items.extend(page.items)
            self._cursor = page.next_cursor
            self._finished = page.next_cursor is None

        return self._items.popleft()
