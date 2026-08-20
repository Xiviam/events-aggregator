from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from events_aggregator.db.models import EventRecord, TicketRecord
from events_aggregator.db.session import create_database
from events_aggregator.domain.models import Event, Place, Ticket
from events_aggregator.repositories import (
    SQLAlchemyEventRepository,
    SQLAlchemyTicketRepository,
)
from events_aggregator.worker import PostgresAdvisoryLock


@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1",
    reason="Set RUN_POSTGRES_TESTS=1 for the PostgreSQL integration test",
)
async def test_postgres_event_upsert_filter_and_ticket_lifecycle() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine, session_factory = create_database(database_url)
    suffix = uuid4().hex
    event_id = f"integration-event-{suffix}"
    ticket_id = f"integration-ticket-{suffix}"
    event_time = datetime(2099, 1, 10, 18, 0, tzinfo=timezone.utc)
    event = Event(
        id=event_id,
        name="Integration event",
        place=Place(
            id=f"integration-place-{suffix}",
            name="Integration hall",
            city="Moscow",
            address="1 Integration Street",
            seats_pattern="A1-10",
        ),
        event_time=event_time,
        registration_deadline=event_time - timedelta(days=1),
        status="published",
        number_of_visitors=1,
        changed_at=event_time - timedelta(days=30),
    )

    try:
        async with session_factory() as session:
            events = SQLAlchemyEventRepository(session)
            tickets = SQLAlchemyTicketRepository(session)
            await events.upsert_many([event])
            await events.upsert_many([replace(event, name="Updated event", number_of_visitors=2)])

            stored_event = await events.get(event_id)
            assert stored_event is not None
            assert stored_event.name == "Updated event"
            assert stored_event.number_of_visitors == 2

            page = await events.list(event_time.date(), offset=0, limit=100)
            assert event_id in {item.id for item in page.items}

            ticket = Ticket(
                id=ticket_id,
                event_id=event_id,
                first_name="Ivan",
                last_name="Ivanov",
                email="integration@example.com",
                seat="A1",
                created_at=datetime.now(timezone.utc),
            )
            await tickets.create(ticket)
            assert await tickets.get(ticket_id) == ticket

            with pytest.raises(IntegrityError):
                await tickets.create(ticket)
            assert await tickets.get(ticket_id) == ticket

            cancelled_at = datetime.now(timezone.utc)
            await tickets.mark_cancelled(ticket_id, cancelled_at)
            stored_ticket = await tickets.get(ticket_id)
            assert stored_ticket is not None
            assert stored_ticket.cancelled_at == cancelled_at
    finally:
        async with session_factory() as cleanup_session:
            await cleanup_session.execute(delete(TicketRecord).where(TicketRecord.id == ticket_id))
            await cleanup_session.execute(delete(EventRecord).where(EventRecord.id == event_id))
            await cleanup_session.commit()
        await engine.dispose()


@pytest.mark.skipif(
    os.getenv("RUN_POSTGRES_TESTS") != "1",
    reason="Set RUN_POSTGRES_TESTS=1 for the PostgreSQL integration test",
)
async def test_postgres_advisory_lock_excludes_another_connection() -> None:
    engine, _ = create_database(os.environ["DATABASE_URL"])
    first_lock = PostgresAdvisoryLock(engine, key=773_014_299)
    second_lock = PostgresAdvisoryLock(engine, key=773_014_299)
    try:
        async with first_lock.acquire() as first_acquired:
            assert first_acquired is True
            async with second_lock.acquire() as second_acquired:
                assert second_acquired is False
        async with second_lock.acquire() as acquired_after_release:
            assert acquired_after_release is True
    finally:
        await engine.dispose()
