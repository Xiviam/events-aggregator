from __future__ import annotations

from events_aggregator.application.cache import AsyncTTLCache
from events_aggregator.domain.errors import EventNotFoundError
from events_aggregator.domain.protocols import EventRepository, EventsProvider


class GetAvailableSeatsUseCase:
    def __init__(
        self,
        events: EventRepository,
        provider: EventsProvider,
        cache: AsyncTTLCache[str, tuple[str, ...]],
    ) -> None:
        self._events = events
        self._provider = provider
        self._cache = cache

    async def execute(self, event_id: str) -> list[str]:
        if await self._events.get(event_id) is None:
            raise EventNotFoundError(f"Event {event_id!r} was not found")

        async def load() -> tuple[str, ...]:
            return tuple(await self._provider.available_seats(event_id))

        return list(await self._cache.get_or_load(event_id, load))
