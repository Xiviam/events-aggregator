from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from events_aggregator.domain.errors import (
    EventNotFoundError,
    EventUnavailableError,
    ProviderNotFoundError,
    RegistrationClosedError,
    TicketNotFoundError,
)
from events_aggregator.domain.models import Ticket
from events_aggregator.domain.protocols import EventRepository, EventsProvider, TicketRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreateTicketCommand:
    event_id: str
    first_name: str
    last_name: str
    email: str
    seat: str


class CreateTicketUseCase:
    def __init__(
        self,
        provider: EventsProvider,
        events: EventRepository,
        tickets: TicketRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._events = events
        self._tickets = tickets
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def execute(self, command: CreateTicketCommand) -> str:
        event = await self._events.get(command.event_id)
        if event is None:
            raise EventNotFoundError(f"Event {command.event_id!r} was not found")
        if event.status.lower() != "published":
            raise EventUnavailableError("Event is not published")

        now = self._clock()
        if event.registration_deadline <= now:
            raise RegistrationClosedError("Registration deadline has passed")

        ticket_id = await self._provider.register(
            event_id=event.id,
            first_name=command.first_name,
            last_name=command.last_name,
            email=command.email,
            seat=command.seat,
        )
        ticket = Ticket(
            id=ticket_id,
            event_id=event.id,
            first_name=command.first_name,
            last_name=command.last_name,
            email=command.email,
            seat=command.seat,
            created_at=now,
        )
        try:
            await self._tickets.create(ticket)
        except Exception:
            try:
                await self._provider.cancel(event.id, ticket_id)
            except Exception:
                logger.exception(
                    "Could not compensate provider registration after local persistence failure"
                )
            raise
        return ticket_id


class CancelTicketUseCase:
    def __init__(
        self,
        provider: EventsProvider,
        tickets: TicketRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._tickets = tickets
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def execute(self, ticket_id: str) -> bool:
        ticket = await self._tickets.get(ticket_id)
        if ticket is None:
            raise TicketNotFoundError(f"Ticket {ticket_id!r} was not found")
        if ticket.is_cancelled:
            return True
        try:
            await self._provider.cancel(ticket.event_id, ticket.id)
        except ProviderNotFoundError:
            logger.info(
                "Provider ticket was already absent during idempotent cancellation: ticket_id=%s",
                ticket.id,
            )
        await self._tickets.mark_cancelled(ticket.id, self._clock())
        return True
