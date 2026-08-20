from __future__ import annotations

from datetime import date

from events_aggregator.domain.errors import EventNotFoundError
from events_aggregator.domain.models import Event, EventPage
from events_aggregator.domain.protocols import EventRepository


class ListEventsUseCase:
    def __init__(self, events: EventRepository) -> None:
        self._events = events

    async def execute(self, date_from: date | None, page: int, page_size: int) -> EventPage:
        return await self._events.list(
            date_from=date_from,
            offset=(page - 1) * page_size,
            limit=page_size,
        )


class GetEventUseCase:
    def __init__(self, events: EventRepository) -> None:
        self._events = events

    async def execute(self, event_id: str) -> Event:
        event = await self._events.get(event_id)
        if event is None:
            raise EventNotFoundError(f"Event {event_id!r} was not found")
        return event
