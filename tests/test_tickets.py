from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from events_aggregator.application.tickets import (
    CancelTicketUseCase,
    CreateTicketCommand,
    CreateTicketUseCase,
)
from events_aggregator.domain.errors import EventNotFoundError, ProviderNotFoundError
from events_aggregator.domain.protocols import EventRepository, EventsProvider, TicketRepository


def command() -> CreateTicketCommand:
    return CreateTicketCommand(
        event_id="event-1",
        first_name="Ivan",
        last_name="Ivanov",
        email="ivan@example.com",
        seat="A15",
    )


async def test_create_ticket_registers_then_persists(
    event_factory,
    now: datetime,
) -> None:
    provider = AsyncMock(spec=EventsProvider)
    provider.register.return_value = "ticket-42"
    events = AsyncMock(spec=EventRepository)
    events.get.return_value = event_factory("event-1")
    tickets = AsyncMock(spec=TicketRepository)

    ticket_id = await CreateTicketUseCase(
        provider,
        events,
        tickets,
        clock=Mock(return_value=now),
    ).execute(command())

    assert ticket_id == "ticket-42"
    provider.register.assert_awaited_once_with(
        event_id="event-1",
        first_name="Ivan",
        last_name="Ivanov",
        email="ivan@example.com",
        seat="A15",
    )
    saved_ticket = tickets.create.await_args.args[0]
    assert saved_ticket.id == "ticket-42"
    assert saved_ticket.event_id == "event-1"
    assert saved_ticket.created_at == now


async def test_create_ticket_compensates_when_local_persistence_fails(
    event_factory,
    now: datetime,
) -> None:
    provider = AsyncMock(spec=EventsProvider)
    provider.register.return_value = "ticket-42"
    events = AsyncMock(spec=EventRepository)
    events.get.return_value = event_factory("event-1")
    tickets = AsyncMock(spec=TicketRepository)
    tickets.create.side_effect = RuntimeError("database write failed")

    with pytest.raises(RuntimeError, match="database write failed"):
        await CreateTicketUseCase(
            provider,
            events,
            tickets,
            clock=Mock(return_value=now),
        ).execute(command())

    provider.cancel.assert_awaited_once_with("event-1", "ticket-42")


async def test_create_ticket_rejects_unknown_event() -> None:
    provider = AsyncMock(spec=EventsProvider)
    events = AsyncMock(spec=EventRepository)
    events.get.return_value = None
    tickets = AsyncMock(spec=TicketRepository)

    with pytest.raises(EventNotFoundError):
        await CreateTicketUseCase(provider, events, tickets).execute(command())

    provider.register.assert_not_awaited()
    tickets.create.assert_not_awaited()


async def test_cancel_ticket_calls_provider_before_marking_local_ticket(
    ticket_factory,
    now: datetime,
) -> None:
    provider = AsyncMock(spec=EventsProvider)
    tickets = AsyncMock(spec=TicketRepository)
    tickets.get.return_value = ticket_factory()

    result = await CancelTicketUseCase(
        provider,
        tickets,
        clock=Mock(return_value=now),
    ).execute("ticket-1")

    assert result is True
    provider.cancel.assert_awaited_once_with("event-1", "ticket-1")
    tickets.mark_cancelled.assert_awaited_once_with("ticket-1", now)


async def test_cancel_ticket_recovers_after_local_write_failure(
    ticket_factory,
    now: datetime,
) -> None:
    provider = AsyncMock(spec=EventsProvider)
    provider.cancel.side_effect = [True, ProviderNotFoundError("already absent")]
    tickets = AsyncMock(spec=TicketRepository)
    tickets.get.return_value = ticket_factory()
    tickets.mark_cancelled.side_effect = [RuntimeError("database down"), None]
    use_case = CancelTicketUseCase(provider, tickets, clock=Mock(return_value=now))

    with pytest.raises(RuntimeError, match="database down"):
        await use_case.execute("ticket-1")

    assert await use_case.execute("ticket-1") is True
    assert provider.cancel.await_count == 2
    assert tickets.mark_cancelled.await_count == 2
