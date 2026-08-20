from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from events_aggregator.api.dependencies import (
    get_event_repository,
    get_provider,
    get_seats_cache,
    get_session,
    get_sync_coordinator,
    get_ticket_repository,
)
from events_aggregator.api.errors import register_error_handlers
from events_aggregator.api.routes import router
from events_aggregator.application.cache import AsyncTTLCache
from events_aggregator.domain.errors import ProviderError, SyncInProgressError
from events_aggregator.domain.models import EventPage, SyncResult
from events_aggregator.domain.protocols import EventRepository, EventsProvider, TicketRepository
from events_aggregator.worker import SyncCoordinator


@pytest.fixture
def api_context() -> SimpleNamespace:
    session = AsyncMock(spec=AsyncSession)
    events = AsyncMock(spec=EventRepository)
    tickets = AsyncMock(spec=TicketRepository)
    provider = AsyncMock(spec=EventsProvider)
    coordinator = AsyncMock(spec=SyncCoordinator)
    cache = AsyncTTLCache[str, tuple[str, ...]](ttl_seconds=30)
    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    app.dependency_overrides = {
        get_session: lambda: session,
        get_event_repository: lambda: events,
        get_ticket_repository: lambda: tickets,
        get_provider: lambda: provider,
        get_seats_cache: lambda: cache,
        get_sync_coordinator: lambda: coordinator,
    }
    return SimpleNamespace(
        app=app,
        session=session,
        events=events,
        tickets=tickets,
        provider=provider,
        coordinator=coordinator,
    )


@pytest.fixture
async def api_client(api_context: SimpleNamespace):
    transport = httpx.ASGITransport(app=api_context.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_health(api_client: httpx.AsyncClient, api_context: SimpleNamespace) -> None:
    response = await api_client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    api_context.session.execute.assert_awaited_once()


async def test_manual_sync(api_client: httpx.AsyncClient, api_context: SimpleNamespace) -> None:
    watermark = datetime.fromisoformat("2026-08-20T10:00:00+00:00")
    api_context.coordinator.run.return_value = SyncResult(
        processed=3,
        last_changed_at=watermark,
    )

    response = await api_client.post("/api/sync/trigger")

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "processed": 3,
        "last_changed_at": "2026-08-20T10:00:00Z",
    }
    api_context.coordinator.run.assert_awaited_once_with()


async def test_list_events_returns_pagination_links_and_local_results(
    api_client: httpx.AsyncClient,
    api_context: SimpleNamespace,
    event_factory,
) -> None:
    api_context.events.list.return_value = EventPage(
        items=[event_factory("event-1"), event_factory("event-2")],
        count=3,
    )

    response = await api_client.get(
        "/api/events",
        params={"date_from": "2026-08-01", "page": 1, "page_size": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 3
    assert [event["id"] for event in payload["results"]] == ["event-1", "event-2"]
    assert "seats_pattern" not in payload["results"][0]["place"]
    assert payload["previous"] is None
    assert parse_qs(urlsplit(payload["next"]).query) == {
        "date_from": ["2026-08-01"],
        "page": ["2"],
        "page_size": ["2"],
    }
    api_context.events.list.assert_awaited_once_with(
        date_from=date(2026, 8, 1),
        offset=0,
        limit=2,
    )


async def test_event_details_and_seats(
    api_client: httpx.AsyncClient,
    api_context: SimpleNamespace,
    event_factory,
) -> None:
    event = event_factory("event-1")
    api_context.events.get.return_value = event
    api_context.provider.available_seats.return_value = ["A1", "A3"]

    detail_response = await api_client.get("/api/events/event-1")
    seats_response = await api_client.get("/api/events/event-1/seats")

    assert detail_response.status_code == 200
    assert detail_response.json()["place"]["seats_pattern"] == "A1-100"
    assert seats_response.status_code == 200
    assert seats_response.json() == {
        "event_id": "event-1",
        "available_seats": ["A1", "A3"],
    }
    api_context.provider.available_seats.assert_awaited_once_with("event-1")


async def test_create_and_cancel_ticket_endpoints(
    api_client: httpx.AsyncClient,
    api_context: SimpleNamespace,
    event_factory,
    ticket_factory,
) -> None:
    event = event_factory(
        "event-1",
        registration_deadline=datetime.now().astimezone() + timedelta(days=30),
    )
    api_context.events.get.return_value = event
    api_context.provider.register.return_value = "ticket-42"

    create_response = await api_client.post(
        "/api/tickets",
        json={
            "event_id": "event-1",
            "first_name": " Ivan ",
            "last_name": " Ivanov ",
            "email": "ivan@example.com",
            "seat": " A15 ",
        },
    )

    assert create_response.status_code == 201
    assert create_response.json() == {"ticket_id": "ticket-42"}
    api_context.provider.register.assert_awaited_once_with(
        event_id="event-1",
        first_name="Ivan",
        last_name="Ivanov",
        email="ivan@example.com",
        seat="A15",
    )

    api_context.tickets.get.return_value = ticket_factory(ticket_id="ticket-42")
    cancel_response = await api_client.delete("/api/tickets/ticket-42")

    assert cancel_response.status_code == 200
    assert cancel_response.json() == {"success": True}
    api_context.provider.cancel.assert_awaited_once_with("event-1", "ticket-42")


async def test_ticket_payload_validation_happens_before_dependencies(
    api_client: httpx.AsyncClient,
    api_context: SimpleNamespace,
) -> None:
    response = await api_client.post(
        "/api/tickets",
        json={
            "event_id": "event-1",
            "first_name": "Ivan",
            "last_name": "Ivanov",
            "email": "not-an-email",
            "seat": "A1",
        },
    )

    assert response.status_code == 422
    api_context.events.get.assert_not_awaited()
    api_context.provider.register.assert_not_awaited()


async def test_production_error_handlers(
    api_client: httpx.AsyncClient,
    api_context: SimpleNamespace,
    event_factory,
) -> None:
    api_context.events.get.return_value = None
    not_found = await api_client.get("/api/events/missing")
    assert not_found.status_code == 404

    api_context.events.get.return_value = event_factory()
    api_context.provider.available_seats.side_effect = ProviderError("provider offline")
    provider_failure = await api_client.get("/api/events/event-1/seats")
    assert provider_failure.status_code == 502

    api_context.coordinator.run.side_effect = SyncInProgressError("already running")
    in_progress = await api_client.post("/api/sync/trigger")
    assert in_progress.status_code == 202
    assert in_progress.json() == {"status": "already_running"}


async def test_health_returns_503_when_database_is_unavailable(
    api_client: httpx.AsyncClient,
    api_context: SimpleNamespace,
) -> None:
    api_context.session.execute.side_effect = RuntimeError("database offline")

    response = await api_client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
