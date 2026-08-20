from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.ext.asyncio import AsyncSession

from events_aggregator.db.models import EventRecord, SyncMetadataRecord, TicketRecord
from events_aggregator.domain.errors import TicketNotFoundError
from events_aggregator.domain.models import Event, EventPage, Place, SyncMetadata, Ticket


class SQLAlchemyEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, date_from: date | None, offset: int, limit: int) -> EventPage:
        filters = []
        if date_from is not None:
            lower_bound = datetime.combine(date_from, time.min).replace(tzinfo=timezone.utc)
            filters.append(EventRecord.event_time >= lower_bound)

        count_statement = select(func.count()).select_from(EventRecord).where(*filters)
        count = int((await self._session.scalar(count_statement)) or 0)
        statement = (
            select(EventRecord)
            .where(*filters)
            .order_by(EventRecord.event_time, EventRecord.id)
            .offset(offset)
            .limit(limit)
        )
        records = (await self._session.scalars(statement)).all()
        return EventPage(items=[_event_to_domain(record) for record in records], count=count)

    async def get(self, event_id: str) -> Event | None:
        record = await self._session.get(EventRecord, event_id)
        return _event_to_domain(record) if record is not None else None

    async def upsert_many(self, events: Sequence[Event]) -> None:
        unique_events = {event.id: event for event in events}
        if not unique_events:
            return

        rows = [_event_values(event) for event in unique_events.values()]
        statement = postgres_insert(EventRecord).values(rows)
        excluded = statement.excluded
        statement = statement.on_conflict_do_update(
            index_elements=[EventRecord.id],
            set_={
                "name": excluded.name,
                "place_id": excluded.place_id,
                "place_name": excluded.place_name,
                "place_city": excluded.place_city,
                "place_address": excluded.place_address,
                "place_seats_pattern": excluded.place_seats_pattern,
                "event_time": excluded.event_time,
                "registration_deadline": excluded.registration_deadline,
                "status": excluded.status,
                "number_of_visitors": excluded.number_of_visitors,
                "provider_changed_at": excluded.provider_changed_at,
                "synced_at": func.now(),
            },
        )
        try:
            await self._session.execute(statement)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise


class SQLAlchemyTicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, ticket_id: str) -> Ticket | None:
        record = await self._session.get(TicketRecord, ticket_id)
        return _ticket_to_domain(record) if record is not None else None

    async def create(self, ticket: Ticket) -> None:
        try:
            self._session.add(
                TicketRecord(
                    id=ticket.id,
                    event_id=ticket.event_id,
                    first_name=ticket.first_name,
                    last_name=ticket.last_name,
                    email=ticket.email,
                    seat=ticket.seat,
                    created_at=ticket.created_at,
                    cancelled_at=ticket.cancelled_at,
                )
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def mark_cancelled(self, ticket_id: str, cancelled_at: datetime) -> None:
        statement = (
            update(TicketRecord)
            .where(TicketRecord.id == ticket_id)
            .values(cancelled_at=cancelled_at)
        )
        try:
            result = await self._session.execute(statement)
            if result.rowcount != 1:
                raise TicketNotFoundError(f"Ticket {ticket_id!r} was not found")
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise


class SQLAlchemySyncMetadataRepository:
    _ROW_ID = 1

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self) -> SyncMetadata | None:
        record = await self._session.get(SyncMetadataRecord, self._ROW_ID)
        if record is None:
            return None
        return SyncMetadata(
            last_sync_time=record.last_sync_time,
            last_changed_at=record.last_changed_at,
            sync_status=record.sync_status,
            error=record.error,
            started_at=record.started_at,
        )

    async def mark_running(self, started_at: datetime) -> None:
        await self._upsert(
            sync_status="running",
            started_at=started_at,
            error=None,
        )

    async def mark_success(self, completed_at: datetime, last_changed_at: datetime) -> None:
        await self._upsert(
            sync_status="success",
            last_sync_time=completed_at,
            last_changed_at=last_changed_at,
            error=None,
        )

    async def mark_failed(self, completed_at: datetime, error: str) -> None:
        await self._upsert(
            sync_status="failed",
            last_sync_time=completed_at,
            error=error[:2000],
        )

    async def _upsert(self, **values: object) -> None:
        insert_values = {"id": self._ROW_ID, **values}
        statement = postgres_insert(SyncMetadataRecord).values(**insert_values)
        statement = statement.on_conflict_do_update(
            index_elements=[SyncMetadataRecord.id],
            set_=values,
        )
        try:
            await self._session.execute(statement)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise


def _event_values(event: Event) -> dict[str, object]:
    return {
        "id": event.id,
        "name": event.name,
        "place_id": event.place.id,
        "place_name": event.place.name,
        "place_city": event.place.city,
        "place_address": event.place.address,
        "place_seats_pattern": event.place.seats_pattern,
        "event_time": event.event_time,
        "registration_deadline": event.registration_deadline,
        "status": event.status,
        "number_of_visitors": event.number_of_visitors,
        "provider_changed_at": event.changed_at,
    }


def _event_to_domain(record: EventRecord) -> Event:
    return Event(
        id=record.id,
        name=record.name,
        place=Place(
            id=record.place_id,
            name=record.place_name,
            city=record.place_city,
            address=record.place_address,
            seats_pattern=record.place_seats_pattern,
        ),
        event_time=record.event_time,
        registration_deadline=record.registration_deadline,
        status=record.status,
        number_of_visitors=record.number_of_visitors,
        changed_at=record.provider_changed_at,
    )


def _ticket_to_domain(record: TicketRecord) -> Ticket:
    return Ticket(
        id=record.id,
        event_id=record.event_id,
        first_name=record.first_name,
        last_name=record.last_name,
        email=record.email,
        seat=record.seat,
        created_at=record.created_at,
        cancelled_at=record.cancelled_at,
    )
