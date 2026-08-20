from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from events_aggregator.domain.models import Event, EventPage, SyncMetadata, Ticket


class EventRepository(Protocol):
    async def list(self, date_from: date | None, offset: int, limit: int) -> EventPage: ...

    async def get(self, event_id: str) -> Event | None: ...

    async def upsert_many(self, events: Sequence[Event]) -> None: ...


class TicketRepository(Protocol):
    async def get(self, ticket_id: str) -> Ticket | None: ...

    async def create(self, ticket: Ticket) -> None: ...

    async def mark_cancelled(self, ticket_id: str, cancelled_at: datetime) -> None: ...


class SyncMetadataRepository(Protocol):
    async def get(self) -> SyncMetadata | None: ...

    async def mark_running(self, started_at: datetime) -> None: ...

    async def mark_success(self, completed_at: datetime, last_changed_at: datetime) -> None: ...

    async def mark_failed(self, completed_at: datetime, error: str) -> None: ...


class EventsProvider(Protocol):
    async def available_seats(self, event_id: str) -> list[str]: ...

    async def register(
        self,
        event_id: str,
        first_name: str,
        last_name: str,
        email: str,
        seat: str,
    ) -> str: ...

    async def cancel(self, event_id: str, ticket_id: str) -> bool: ...
