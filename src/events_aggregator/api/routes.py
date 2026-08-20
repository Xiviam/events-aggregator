from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import text

from events_aggregator.api.dependencies import (
    EventRepositoryDependency,
    ProviderDependency,
    SeatsCacheDependency,
    SessionDependency,
    SyncCoordinatorDependency,
    TicketRepositoryDependency,
)
from events_aggregator.api.schemas import (
    AvailableSeatsResponse,
    CancelTicketResponse,
    CreateTicketRequest,
    CreateTicketResponse,
    EventDetailResponse,
    EventListItemResponse,
    EventsPageResponse,
    HealthResponse,
    SyncTriggerResponse,
)
from events_aggregator.application.events import GetEventUseCase, ListEventsUseCase
from events_aggregator.application.seats import GetAvailableSeatsUseCase
from events_aggregator.application.tickets import (
    CancelTicketUseCase,
    CreateTicketCommand,
    CreateTicketUseCase,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
DateFromParameter = Annotated[Optional[date], Query()]
PageParameter = Annotated[int, Query(ge=1)]
PageSizeParameter = Annotated[int, Query(ge=1, le=100)]


@router.get("/health", response_model=HealthResponse, tags=["service"])
async def health(session: SessionDependency) -> HealthResponse:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database health check failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc
    return HealthResponse(status="ok", database="ok")


@router.post("/sync/trigger", response_model=SyncTriggerResponse, tags=["sync"])
async def trigger_sync(
    coordinator: SyncCoordinatorDependency,
) -> SyncTriggerResponse:
    result = await coordinator.run()
    return SyncTriggerResponse(
        status="success",
        processed=result.processed,
        last_changed_at=result.last_changed_at,
    )


@router.get("/events", response_model=EventsPageResponse, tags=["events"])
async def list_events(
    request: Request,
    events: EventRepositoryDependency,
    date_from: DateFromParameter = None,
    page: PageParameter = 1,
    page_size: PageSizeParameter = 20,
) -> EventsPageResponse:
    result = await ListEventsUseCase(events).execute(date_from, page, page_size)

    def page_url(page_number: int) -> str:
        return str(
            request.url.include_query_params(
                page=page_number,
                page_size=page_size,
            )
        )

    next_url = page_url(page + 1) if page * page_size < result.count else None
    previous_url = page_url(page - 1) if page > 1 else None
    return EventsPageResponse(
        count=result.count,
        next=next_url,
        previous=previous_url,
        results=[EventListItemResponse.model_validate(event) for event in result.items],
    )


@router.get("/events/{event_id}", response_model=EventDetailResponse, tags=["events"])
async def get_event(
    event_id: str,
    events: EventRepositoryDependency,
) -> EventDetailResponse:
    event = await GetEventUseCase(events).execute(event_id)
    return EventDetailResponse.model_validate(event)


@router.get(
    "/events/{event_id}/seats",
    response_model=AvailableSeatsResponse,
    tags=["events"],
)
async def get_available_seats(
    event_id: str,
    events: EventRepositoryDependency,
    provider: ProviderDependency,
    cache: SeatsCacheDependency,
) -> AvailableSeatsResponse:
    seats = await GetAvailableSeatsUseCase(events, provider, cache).execute(event_id)
    return AvailableSeatsResponse(event_id=event_id, available_seats=seats)


@router.post(
    "/tickets",
    response_model=CreateTicketResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["tickets"],
)
async def create_ticket(
    payload: CreateTicketRequest,
    events: EventRepositoryDependency,
    tickets: TicketRepositoryDependency,
    provider: ProviderDependency,
) -> CreateTicketResponse:
    command = CreateTicketCommand(
        event_id=payload.event_id,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=str(payload.email),
        seat=payload.seat,
    )
    ticket_id = await CreateTicketUseCase(provider, events, tickets).execute(command)
    return CreateTicketResponse(ticket_id=ticket_id)


@router.delete(
    "/tickets/{ticket_id}",
    response_model=CancelTicketResponse,
    tags=["tickets"],
)
async def cancel_ticket(
    ticket_id: str,
    tickets: TicketRepositoryDependency,
    provider: ProviderDependency,
) -> CancelTicketResponse:
    success = await CancelTicketUseCase(provider, tickets).execute(ticket_id)
    return CancelTicketResponse(success=success)
