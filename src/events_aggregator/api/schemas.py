from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class HealthResponse(BaseModel):
    status: str
    database: str


class PlaceListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    city: str
    address: str


class PlaceDetailResponse(PlaceListResponse):
    seats_pattern: Optional[str]


class EventListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    place: PlaceListResponse
    event_time: datetime
    registration_deadline: datetime
    status: str
    number_of_visitors: int


class EventDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    place: PlaceDetailResponse
    event_time: datetime
    registration_deadline: datetime
    status: str
    number_of_visitors: int


class EventsPageResponse(BaseModel):
    count: int
    next: Optional[str]
    previous: Optional[str]
    results: list[EventListItemResponse]


class AvailableSeatsResponse(BaseModel):
    event_id: str
    available_seats: list[str]


class CreateTicketRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=255)
    first_name: str = Field(min_length=1, max_length=128)
    last_name: str = Field(min_length=1, max_length=128)
    email: EmailStr = Field(max_length=255)
    seat: str = Field(min_length=1, max_length=16)


class CreateTicketResponse(BaseModel):
    ticket_id: str


class CancelTicketResponse(BaseModel):
    success: bool


class SyncTriggerResponse(BaseModel):
    status: str
    processed: int
    last_changed_at: datetime


class ErrorResponse(BaseModel):
    detail: str
