from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from events_aggregator.application.cache import AsyncTTLCache
from events_aggregator.provider.client import EventsProviderClient
from events_aggregator.repositories import (
    SQLAlchemyEventRepository,
    SQLAlchemyTicketRepository,
)
from events_aggregator.worker import SyncCoordinator


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


def get_event_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SQLAlchemyEventRepository:
    return SQLAlchemyEventRepository(session)


def get_ticket_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SQLAlchemyTicketRepository:
    return SQLAlchemyTicketRepository(session)


def get_provider(request: Request) -> EventsProviderClient:
    return request.app.state.provider_client


def get_seats_cache(request: Request) -> AsyncTTLCache[str, tuple[str, ...]]:
    return request.app.state.seats_cache


def get_sync_coordinator(request: Request) -> SyncCoordinator:
    return request.app.state.sync_coordinator


SessionDependency = Annotated[AsyncSession, Depends(get_session)]
EventRepositoryDependency = Annotated[
    SQLAlchemyEventRepository,
    Depends(get_event_repository),
]
TicketRepositoryDependency = Annotated[
    SQLAlchemyTicketRepository,
    Depends(get_ticket_repository),
]
ProviderDependency = Annotated[EventsProviderClient, Depends(get_provider)]
SeatsCacheDependency = Annotated[
    AsyncTTLCache[str, tuple[str, ...]],
    Depends(get_seats_cache),
]
SyncCoordinatorDependency = Annotated[SyncCoordinator, Depends(get_sync_coordinator)]
