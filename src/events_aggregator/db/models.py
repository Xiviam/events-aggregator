from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from events_aggregator.db.base import Base


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_event_time_id", "event_time", "id"),)

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    place_id: Mapped[str] = mapped_column(String(255), nullable=False)
    place_name: Mapped[str] = mapped_column(String(500), nullable=False)
    place_city: Mapped[str] = mapped_column(String(255), nullable=False)
    place_address: Mapped[str] = mapped_column(String(1000), nullable=False)
    place_seats_pattern: Mapped[Optional[str]] = mapped_column(Text)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    registration_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    number_of_visitors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TicketRecord(Base):
    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("events.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    seat: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class SyncMetadataRecord(Base):
    __tablename__ = "sync_metadata"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    last_sync_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="never", server_default="never"
    )
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
