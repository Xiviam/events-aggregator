from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from events_aggregator.application.sync import SyncEventsUseCase
from events_aggregator.domain.errors import SyncInProgressError
from events_aggregator.domain.models import SyncResult
from events_aggregator.provider.paginator import EventsPageSource
from events_aggregator.repositories import (
    SQLAlchemyEventRepository,
    SQLAlchemySyncMetadataRepository,
)

logger = logging.getLogger(__name__)
SYNC_ADVISORY_LOCK_KEY = 773_014_290


class PostgresAdvisoryLock:
    def __init__(self, engine: AsyncEngine, key: int = SYNC_ADVISORY_LOCK_KEY) -> None:
        self._engine = engine
        self._key = key

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[bool]:
        async with self._engine.connect() as connection:
            acquired = bool(
                await connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": self._key},
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": self._key},
                    )


class SyncCoordinator:
    """Coordinates use-case execution across tasks and application replicas."""

    def __init__(
        self,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
        provider: EventsPageSource,
        batch_size: int,
        overlap_seconds: float,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider
        self._batch_size = batch_size
        self._overlap_seconds = overlap_seconds
        self._local_lock = asyncio.Lock()
        self._database_lock = PostgresAdvisoryLock(engine)

    async def run(self) -> SyncResult:
        if self._local_lock.locked():
            raise SyncInProgressError("Event synchronization is already running")

        async with self._local_lock, self._database_lock.acquire() as acquired:
            if not acquired:
                raise SyncInProgressError("Event synchronization is running in another replica")
            async with self._session_factory() as session:
                use_case = SyncEventsUseCase(
                    provider=self._provider,
                    events=SQLAlchemyEventRepository(session),
                    metadata=SQLAlchemySyncMetadataRepository(session),
                    batch_size=self._batch_size,
                    overlap_seconds=self._overlap_seconds,
                )
                return await use_case.execute()

    async def seconds_until_due(self, interval_seconds: float) -> float:
        async with self._session_factory() as session:
            state = await SQLAlchemySyncMetadataRepository(session).get()
        if state is None:
            return 0.0
        if state.sync_status == "running":
            stale_after = min(3_600.0, interval_seconds)
            if state.started_at is not None:
                running_for = (datetime.now(timezone.utc) - state.started_at).total_seconds()
                if running_for >= stale_after:
                    return 0.0
            return min(60.0, interval_seconds)
        if state.last_sync_time is None:
            return 0.0
        if state.sync_status == "failed":
            return min(300.0, interval_seconds)
        elapsed = (datetime.now(timezone.utc) - state.last_sync_time).total_seconds()
        return max(0.0, interval_seconds - elapsed)


class DailySyncWorker:
    def __init__(
        self,
        coordinator: SyncCoordinator,
        interval_seconds: float = 86_400,
        run_on_startup: bool = True,
    ) -> None:
        self._coordinator = coordinator
        self._interval_seconds = interval_seconds
        self._run_on_startup = run_on_startup
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run(), name="daily-event-sync")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self) -> None:
        if not self._run_on_startup and await self._wait(self._interval_seconds):
            return
        while not self._stop_event.is_set():
            try:
                delay = await self._coordinator.seconds_until_due(self._interval_seconds)
            except Exception:
                logger.exception("Could not calculate the next synchronization time")
                delay = min(60.0, self._interval_seconds)
            if delay > 0:
                if await self._wait(delay):
                    return
            else:
                await self._run_once()

    async def _wait(self, delay: float) -> bool:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            return False
        return True

    async def _run_once(self) -> None:
        try:
            await self._coordinator.run()
        except SyncInProgressError:
            logger.info("Scheduled event synchronization skipped because another run is active")
        except Exception:
            logger.exception("Scheduled event synchronization failed")
