from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    city: str
    address: str
    seats_pattern: str | None = None


@dataclass(frozen=True)
class Event:
    id: str
    name: str
    place: Place
    event_time: datetime
    registration_deadline: datetime
    status: str
    number_of_visitors: int
    changed_at: datetime | None = None


@dataclass(frozen=True)
class Ticket:
    id: str
    event_id: str
    first_name: str
    last_name: str
    email: str
    seat: str
    created_at: datetime
    cancelled_at: datetime | None = None

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_at is not None


@dataclass(frozen=True)
class SyncMetadata:
    last_sync_time: datetime | None
    last_changed_at: datetime | None
    sync_status: str
    error: str | None = None
    started_at: datetime | None = None


@dataclass(frozen=True)
class EventPage:
    items: list[Event]
    count: int


@dataclass(frozen=True)
class SyncResult:
    processed: int
    last_changed_at: datetime
