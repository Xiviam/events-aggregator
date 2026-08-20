from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, call

import pytest

from events_aggregator.application.sync import FIRST_SYNC_CHANGED_AT, SyncEventsUseCase
from events_aggregator.domain.protocols import EventRepository, SyncMetadataRepository
from events_aggregator.provider.client import ProviderEventsPage
from events_aggregator.provider.paginator import EventsPageSource


async def test_first_sync_paginates_batches_and_advances_watermark(event_factory) -> None:
    started_at = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(minutes=10)
    events_to_sync = [
        event_factory(
            f"event-{number}",
            changed_at=started_at + timedelta(minutes=number),
        )
        for number in range(1, 4)
    ]
    provider = AsyncMock(spec=EventsPageSource)
    provider.events.side_effect = [
        ProviderEventsPage(items=events_to_sync[:2], next_cursor="next"),
        ProviderEventsPage(items=events_to_sync[2:], next_cursor=None),
    ]
    events = AsyncMock(spec=EventRepository)
    saved_batches: list[list] = []
    events.upsert_many.side_effect = lambda batch: saved_batches.append(list(batch))
    metadata = AsyncMock(spec=SyncMetadataRepository)
    metadata.get.return_value = None
    clock = Mock(side_effect=[started_at, completed_at])

    result = await SyncEventsUseCase(
        provider,
        events,
        metadata,
        batch_size=2,
        clock=clock,
    ).execute()

    assert result.processed == 3
    assert result.last_changed_at == events_to_sync[-1].changed_at
    assert saved_batches == [events_to_sync[:2], events_to_sync[2:]]
    assert provider.events.await_args_list == [
        call(FIRST_SYNC_CHANGED_AT, None),
        call(FIRST_SYNC_CHANGED_AT, "next"),
    ]
    metadata.mark_running.assert_awaited_once_with(started_at)
    metadata.mark_success.assert_awaited_once_with(
        completed_at,
        events_to_sync[-1].changed_at,
    )
    metadata.mark_failed.assert_not_awaited()


async def test_failed_sync_marks_failure_without_success() -> None:
    started_at = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    failed_at = started_at + timedelta(seconds=2)
    provider = AsyncMock(spec=EventsPageSource)
    provider.events.side_effect = RuntimeError("provider down")
    events = AsyncMock(spec=EventRepository)
    metadata = AsyncMock(spec=SyncMetadataRepository)
    metadata.get.return_value = None

    use_case = SyncEventsUseCase(
        provider,
        events,
        metadata,
        clock=Mock(side_effect=[started_at, failed_at]),
    )

    with pytest.raises(RuntimeError, match="provider down"):
        await use_case.execute()

    metadata.mark_failed.assert_awaited_once_with(
        failed_at,
        "RuntimeError: provider down",
    )
    metadata.mark_success.assert_not_awaited()
    events.upsert_many.assert_not_awaited()


async def test_original_sync_error_survives_metadata_failure() -> None:
    started_at = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    failed_at = started_at + timedelta(seconds=2)
    provider = AsyncMock(spec=EventsPageSource)
    provider.events.side_effect = RuntimeError("provider down")
    events = AsyncMock(spec=EventRepository)
    metadata = AsyncMock(spec=SyncMetadataRepository)
    metadata.get.return_value = None
    metadata.mark_failed.side_effect = RuntimeError("database down")

    use_case = SyncEventsUseCase(
        provider,
        events,
        metadata,
        clock=Mock(side_effect=[started_at, failed_at]),
    )

    with pytest.raises(RuntimeError, match="provider down"):
        await use_case.execute()
