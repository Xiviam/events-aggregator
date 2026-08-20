from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from events_aggregator.domain.errors import (
    ProviderConflictError,
    ProviderError,
    ProviderResponseError,
)
from events_aggregator.provider.client import EventsProviderClient


@pytest.fixture
def http_client() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def provider_client(http_client: AsyncMock) -> EventsProviderClient:
    return EventsProviderClient(
        base_url="https://provider.example",
        api_key="test-key",
        http_client=http_client,
    )


async def test_events_maps_payload_and_sends_incremental_parameters(
    provider_client: EventsProviderClient,
    http_client: AsyncMock,
) -> None:
    http_client.request.return_value = httpx.Response(
        200,
        json={
            "results": [
                {
                    "id": "event-1",
                    "name": "Python meetup",
                    "place": {
                        "id": "place-1",
                        "name": "Main hall",
                        "city": "Moscow",
                        "address": "1 Test Street",
                        "seats_pattern": "A1-100",
                    },
                    "event_time": "2026-08-27T18:00:00+03:00",
                    "registration_deadline": "2026-08-26T18:00:00+03:00",
                    "status": "published",
                    "number_of_visitors": 12,
                    "changed_at": "2026-08-20T09:30:00Z",
                }
            ],
            "next_cursor": "cursor-2",
        },
    )

    page = await provider_client.events(
        datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc),
        cursor="cursor-1",
    )

    assert page.next_cursor == "cursor-2"
    assert [event.id for event in page.items] == ["event-1"]
    assert page.items[0].place.seats_pattern == "A1-100"
    assert page.items[0].number_of_visitors == 12
    http_client.request.assert_awaited_once_with(
        "GET",
        "/api/events/",
        params={"changed_at": "2026-08-19", "cursor": "cursor-1"},
        json=None,
        headers={"Accept": "application/json", "X-API-Key": "test-key"},
    )


async def test_register_sends_expected_request(
    provider_client: EventsProviderClient,
    http_client: AsyncMock,
) -> None:
    http_client.request.return_value = httpx.Response(
        201,
        json={"ticket_id": "ticket-42"},
    )

    ticket_id = await provider_client.register(
        event_id="event/with spaces",
        first_name="Ivan",
        last_name="Ivanov",
        email="ivan@example.com",
        seat="A15",
    )

    assert ticket_id == "ticket-42"
    http_client.request.assert_awaited_once_with(
        "POST",
        "/api/events/event%2Fwith%20spaces/register/",
        params=None,
        json={
            "first_name": "Ivan",
            "last_name": "Ivanov",
            "email": "ivan@example.com",
            "seat": "A15",
        },
        headers={"Accept": "application/json", "X-API-Key": "test-key"},
    )


async def test_available_seats_normalizes_objects_and_removes_duplicates(
    provider_client: EventsProviderClient,
    http_client: AsyncMock,
) -> None:
    http_client.request.return_value = httpx.Response(
        200,
        json={
            "available_seats": [
                "A1",
                {"seat": "A2", "available": True},
                {"seat": "A3", "available": False},
                "A1",
            ]
        },
    )

    seats = await provider_client.available_seats("event-1")

    assert seats == ["A1", "A2"]


async def test_provider_errors_are_translated(
    provider_client: EventsProviderClient,
    http_client: AsyncMock,
) -> None:
    http_client.request.return_value = httpx.Response(409, json={"detail": "occupied"})

    with pytest.raises(ProviderConflictError):
        await provider_client.register("event-1", "Ivan", "Ivanov", "i@example.com", "A1")

    request = httpx.Request("GET", "https://provider.example/api/events/")
    http_client.request.side_effect = httpx.ConnectError("offline", request=request)

    with pytest.raises(ProviderError, match="unavailable"):
        await provider_client.events(datetime(2026, 8, 20, tzinfo=timezone.utc))


async def test_provider_bad_request_is_a_business_conflict(
    provider_client: EventsProviderClient,
    http_client: AsyncMock,
) -> None:
    http_client.request.return_value = httpx.Response(400, json={"detail": "seat occupied"})

    with pytest.raises(ProviderConflictError):
        await provider_client.register("event-1", "Ivan", "Ivanov", "i@example.com", "A1")


async def test_token_auth_mode_is_supported(http_client: AsyncMock) -> None:
    http_client.request.return_value = httpx.Response(200, json={"results": [], "next": None})
    client = EventsProviderClient(
        base_url="https://provider.example",
        api_key="legacy-token",
        auth_mode="token",
        http_client=http_client,
    )

    await client.events(datetime(2026, 8, 20, tzinfo=timezone.utc))

    assert http_client.request.await_args.kwargs["headers"]["Authorization"] == (
        "Token legacy-token"
    )


async def test_cancel_requires_explicit_success_confirmation(
    provider_client: EventsProviderClient,
    http_client: AsyncMock,
) -> None:
    http_client.request.return_value = httpx.Response(200, json={})

    with pytest.raises(ProviderResponseError, match="did not confirm"):
        await provider_client.cancel("event-1", "ticket-1")
