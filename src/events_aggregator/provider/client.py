from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from urllib.parse import quote, urljoin, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from events_aggregator.domain.errors import (
    ProviderConflictError,
    ProviderError,
    ProviderNotFoundError,
    ProviderResponseError,
)
from events_aggregator.domain.models import Event, Place


class _ProviderPlace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    city: str
    address: str
    seats_pattern: Optional[str] = None


class _ProviderEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    place: _ProviderPlace
    event_time: datetime
    registration_deadline: datetime
    status: str
    number_of_visitors: int = 0
    changed_at: Optional[datetime] = None

    @field_validator("event_time", "registration_deadline", "changed_at")
    @classmethod
    def datetimes_are_aware(
        cls,
        value: Optional[datetime],
    ) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def to_domain(self) -> Event:
        return Event(
            id=self.id,
            name=self.name,
            place=Place(
                id=self.place.id,
                name=self.place.name,
                city=self.place.city,
                address=self.place.address,
                seats_pattern=self.place.seats_pattern,
            ),
            event_time=self.event_time,
            registration_deadline=self.registration_deadline,
            status=self.status,
            number_of_visitors=self.number_of_visitors,
            changed_at=self.changed_at,
        )


@dataclass(frozen=True)
class ProviderEventsPage:
    items: list[Event]
    next_cursor: str | None


class EventsProviderClient:
    """All HTTP access to the external Events Provider API.

    Pagination links are accepted in addition to opaque cursor values. Absolute
    links must stay on the configured provider origin, so credentials cannot be
    forwarded to an unrelated host.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        auth_mode: Literal["api_key", "token", "bearer"] = "api_key",
        timeout_seconds: float = 10.0,
        events_path: str = "/api/events/",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._events_path = events_path.rstrip("/") + "/"
        self._api_key = api_key
        self._auth_mode = auth_mode
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def events(
        self,
        changed_at: datetime,
        cursor: str | None = None,
    ) -> ProviderEventsPage:
        url, params = self._event_page_request(changed_at, cursor)
        response = await self._request("GET", url, params=params)
        payload = _response_json(response)

        if isinstance(payload, list):
            raw_items = payload
            next_cursor = None
        elif isinstance(payload, dict):
            raw_items = payload.get("results", payload.get("events", []))
            next_cursor = _next_cursor(payload)
        else:
            raise ProviderResponseError("Events response must be an object or a list")

        if not isinstance(raw_items, list):
            raise ProviderResponseError("Events response field 'results' must be a list")

        try:
            items = [_ProviderEvent.model_validate(item).to_domain() for item in raw_items]
        except ValidationError as exc:
            raise ProviderResponseError("Events response has an invalid event") from exc

        return ProviderEventsPage(items=items, next_cursor=next_cursor)

    async def available_seats(self, event_id: str) -> list[str]:
        event_path = f"{self._events_path}{quote(event_id, safe='')}/seats/"
        response = await self._request("GET", event_path)
        payload = _response_json(response)
        if isinstance(payload, dict):
            raw_seats = payload.get("available_seats", payload.get("seats"))
        else:
            raw_seats = payload
        if not isinstance(raw_seats, list):
            raise ProviderResponseError("Seats response must contain a list")

        seats: list[str] = []
        for raw_seat in raw_seats:
            if isinstance(raw_seat, str):
                seats.append(raw_seat)
            elif isinstance(raw_seat, dict) and raw_seat.get("available", True):
                value = raw_seat.get("seat", raw_seat.get("name", raw_seat.get("id")))
                if isinstance(value, str):
                    seats.append(value)
                else:
                    raise ProviderResponseError("Seat object has no string identifier")
            else:
                if not isinstance(raw_seat, dict):
                    raise ProviderResponseError("Seat entries must be strings or objects")

        return list(dict.fromkeys(seats))

    async def register(
        self,
        event_id: str,
        first_name: str,
        last_name: str,
        email: str,
        seat: str,
    ) -> str:
        response = await self._request(
            "POST",
            f"{self._events_path}{quote(event_id, safe='')}/register/",
            json={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "seat": seat,
            },
        )
        payload = _response_json(response)
        if not isinstance(payload, dict):
            raise ProviderResponseError("Registration response must be an object")
        ticket_id = payload.get("ticket_id", payload.get("id"))
        if ticket_id is None and isinstance(payload.get("ticket"), dict):
            ticket_id = payload["ticket"].get("id")
        if not isinstance(ticket_id, str) or not ticket_id:
            raise ProviderResponseError("Registration response has no ticket id")
        return ticket_id

    async def cancel(self, event_id: str, ticket_id: str) -> bool:
        unregister_path = f"{self._events_path}{quote(event_id, safe='')}/unregister/"
        response = await self._request(
            "DELETE",
            unregister_path,
            json={"ticket_id": ticket_id},
        )
        if response.status_code == httpx.codes.NO_CONTENT or not response.content:
            return True
        payload = _response_json(response)
        if isinstance(payload, dict) and payload.get("success") is True:
            return True
        raise ProviderResponseError("Cancellation response did not confirm success")

    def _event_page_request(
        self,
        changed_at: datetime,
        cursor: str | None,
    ) -> tuple[str, dict[str, str] | None]:
        if cursor and _is_pagination_link(cursor):
            return self._safe_pagination_url(cursor), None
        params = {"changed_at": changed_at.date().isoformat()}
        if cursor:
            params["cursor"] = cursor
        return self._events_path, params

    def _safe_pagination_url(self, cursor: str) -> str:
        if cursor.startswith("?"):
            return f"{self._events_path}{cursor}"
        absolute = urljoin(self._base_url, cursor)
        parsed = urlparse(absolute)
        base = urlparse(self._base_url)
        if parsed.hostname != base.hostname:
            raise ProviderResponseError("Provider pagination link changed origin")
        path_and_query = parsed.path
        if parsed.query:
            path_and_query = f"{path_and_query}?{parsed.query}"
        return urljoin(self._base_url, path_and_query)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"Accept": "application/json"}
        if self._api_key:
            if self._auth_mode == "api_key":
                headers["X-API-Key"] = self._api_key
            elif self._auth_mode == "token":
                headers["Authorization"] = f"Token {self._api_key}"
            elif self._auth_mode == "bearer":
                headers["Authorization"] = f"Bearer {self._api_key}"
            else:
                raise ValueError(f"Unsupported provider auth mode: {self._auth_mode}")
        try:
            response = await self._http.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise ProviderError("Events Provider API is unavailable") from exc

        if response.status_code == httpx.codes.NOT_FOUND:
            raise ProviderNotFoundError("Provider resource was not found")
        if response.status_code in {
            httpx.codes.BAD_REQUEST,
            httpx.codes.CONFLICT,
            httpx.codes.UNPROCESSABLE_ENTITY,
        }:
            raise ProviderConflictError("Provider rejected the request")
        if response.is_error:
            raise ProviderError(f"Events Provider API returned HTTP {response.status_code}")
        return response


def _is_pagination_link(cursor: str) -> bool:
    return cursor.startswith(("http://", "https://", "/", "?"))


def _next_cursor(payload: dict[str, Any]) -> str | None:
    value = payload.get("next_cursor", payload.get("next"))
    if value is None and isinstance(payload.get("pagination"), dict):
        pagination = payload["pagination"]
        value = pagination.get("next_cursor", pagination.get("next"))
    if value is None:
        return None
    if not isinstance(value, str):
        raise ProviderResponseError("Pagination cursor must be a string or null")
    return value or None


def _response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderResponseError("Events Provider API returned invalid JSON") from exc
