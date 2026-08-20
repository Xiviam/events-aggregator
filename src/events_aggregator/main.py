from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from events_aggregator.api.errors import register_error_handlers
from events_aggregator.api.routes import router
from events_aggregator.application.cache import AsyncTTLCache
from events_aggregator.config import Settings, get_settings
from events_aggregator.db.session import create_database
from events_aggregator.provider.client import EventsProviderClient
from events_aggregator.worker import DailySyncWorker, SyncCoordinator


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    engine, session_factory = create_database(config.database_url)
    api_key = (
        config.events_provider_api_key.get_secret_value()
        if config.events_provider_api_key is not None
        else None
    )
    provider_client = EventsProviderClient(
        base_url=config.events_provider_base_url,
        api_key=api_key,
        auth_mode=config.events_provider_auth_mode,
        timeout_seconds=config.events_provider_timeout_seconds,
        events_path=config.events_provider_events_path,
    )
    sync_coordinator = SyncCoordinator(
        engine=engine,
        session_factory=session_factory,
        provider=provider_client,
        batch_size=config.sync_batch_size,
        overlap_seconds=config.sync_overlap_seconds,
    )
    sync_worker = DailySyncWorker(
        sync_coordinator,
        interval_seconds=config.sync_interval_seconds,
        run_on_startup=config.sync_run_on_startup,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if config.sync_enabled:
            sync_worker.start()
        try:
            yield
        finally:
            if config.sync_enabled:
                await sync_worker.stop()
            await provider_client.close()
            await engine.dispose()

    application = FastAPI(
        title=config.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = config
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.provider_client = provider_client
    application.state.seats_cache = AsyncTTLCache[str, tuple[str, ...]](
        config.seats_cache_ttl_seconds
    )
    application.state.sync_coordinator = sync_coordinator
    application.include_router(router)
    register_error_handlers(application)
    return application


app = create_app()
