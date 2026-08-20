from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from events_aggregator.worker import DailySyncWorker, SyncCoordinator


async def test_worker_runs_due_sync_on_startup() -> None:
    coordinator = AsyncMock(spec=SyncCoordinator)
    coordinator.seconds_until_due.side_effect = [0.0, 86_400.0]
    synchronized = asyncio.Event()

    async def mark_synchronized():
        synchronized.set()

    coordinator.run.side_effect = mark_synchronized
    worker = DailySyncWorker(coordinator, run_on_startup=True)

    worker.start()
    await asyncio.wait_for(synchronized.wait(), timeout=1)
    await worker.stop()

    coordinator.run.assert_awaited_once_with()


async def test_worker_does_not_repeat_recent_sync_on_restart() -> None:
    coordinator = AsyncMock(spec=SyncCoordinator)
    coordinator.seconds_until_due.return_value = 86_400.0
    worker = DailySyncWorker(coordinator, run_on_startup=True)

    worker.start()
    await asyncio.sleep(0)
    await worker.stop()

    coordinator.run.assert_not_awaited()


async def test_worker_can_disable_startup_catch_up() -> None:
    coordinator = AsyncMock(spec=SyncCoordinator)
    worker = DailySyncWorker(
        coordinator,
        interval_seconds=86_400.0,
        run_on_startup=False,
    )

    worker.start()
    await asyncio.sleep(0)
    await worker.stop()

    coordinator.seconds_until_due.assert_not_awaited()
    coordinator.run.assert_not_awaited()


async def test_worker_can_restart_after_stop() -> None:
    coordinator = AsyncMock(spec=SyncCoordinator)
    coordinator.seconds_until_due.return_value = 86_400.0
    worker = DailySyncWorker(coordinator, run_on_startup=True)

    worker.start()
    await asyncio.sleep(0)
    await worker.stop()
    worker.start()
    await asyncio.sleep(0)
    await worker.stop()

    assert coordinator.seconds_until_due.await_count == 2
