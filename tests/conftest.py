from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from events_aggregator.domain.models import Event, Place, Ticket

FIXED_NOW = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def now() -> datetime:
    return FIXED_NOW


@pytest.fixture
def event_factory():
    def make_event(
        event_id: str = "event-1",
        *,
        status: str = "published",
        registration_deadline: datetime | None = None,
        changed_at: datetime | None = FIXED_NOW,
    ) -> Event:
        return Event(
            id=event_id,
            name=f"Event {event_id}",
            place=Place(
                id=f"place-{event_id}",
                name="Main hall",
                city="Moscow",
                address="1 Test Street",
                seats_pattern="A1-100",
            ),
            event_time=FIXED_NOW + timedelta(days=7),
            registration_deadline=registration_deadline or FIXED_NOW + timedelta(days=6),
            status=status,
            number_of_visitors=5,
            changed_at=changed_at,
        )

    return make_event


@pytest.fixture
def ticket_factory():
    def make_ticket(
        ticket_id: str = "ticket-1",
        *,
        event_id: str = "event-1",
        cancelled_at: datetime | None = None,
    ) -> Ticket:
        return Ticket(
            id=ticket_id,
            event_id=event_id,
            first_name="Ivan",
            last_name="Ivanov",
            email="ivan@example.com",
            seat="A15",
            created_at=FIXED_NOW,
            cancelled_at=cancelled_at,
        )

    return make_ticket
