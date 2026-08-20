from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from events_aggregator.domain.models import Event, SyncResult
from events_aggregator.domain.protocols import EventRepository, SyncMetadataRepository
from events_aggregator.provider.paginator import EventsPageSource, EventsPaginator

logger = logging.getLogger(__name__)
FIRST_SYNC_CHANGED_AT = datetime(2000, 1, 1, tzinfo=timezone.utc)


class SyncEventsUseCase:
    def __init__(
        self,
        provider: EventsPageSource,
        events: EventRepository,
        metadata: SyncMetadataRepository,
        batch_size: int = 100,
        overlap_seconds: float = 1.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._events = events
        self._metadata = metadata
        self._batch_size = batch_size
        self._overlap = timedelta(seconds=overlap_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def execute(self) -> SyncResult:
        state = await self._metadata.get()
        previous_watermark = (
            state.last_changed_at
            if state is not None and state.last_changed_at is not None
            else FIRST_SYNC_CHANGED_AT
        )
        changed_at = max(FIRST_SYNC_CHANGED_AT, previous_watermark - self._overlap)
        started_at = self._clock()
        await self._metadata.mark_running(started_at)
        logger.info("Event synchronization started from changed_at=%s", changed_at.isoformat())

        processed = 0
        batch: list[Event] = []
        latest_changed_at = max(previous_watermark, started_at)
        try:
            async for event in EventsPaginator(self._provider, changed_at):
                batch.append(event)
                processed += 1
                if event.changed_at is not None:
                    latest_changed_at = max(latest_changed_at, event.changed_at)
                if len(batch) >= self._batch_size:
                    await self._events.upsert_many(batch)
                    batch.clear()
            if batch:
                await self._events.upsert_many(batch)

            completed_at = self._clock()
            await self._metadata.mark_success(completed_at, latest_changed_at)
            logger.info(
                "Event synchronization completed: processed=%d last_changed_at=%s",
                processed,
                latest_changed_at.isoformat(),
            )
            return SyncResult(processed=processed, last_changed_at=latest_changed_at)
        except Exception as exc:
            completed_at = self._clock()
            try:
                await self._metadata.mark_failed(
                    completed_at,
                    f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                logger.exception("Could not persist failed synchronization status")
            logger.exception("Event synchronization failed after %d events", processed)
            raise
