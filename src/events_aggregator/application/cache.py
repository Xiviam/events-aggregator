from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Hashable
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

KeyT = TypeVar("KeyT", bound=Hashable)
ValueT = TypeVar("ValueT")


@dataclass(frozen=True)
class _CacheEntry(Generic[ValueT]):
    value: ValueT
    expires_at: float


class AsyncTTLCache(Generic[KeyT, ValueT]):
    """Small in-process TTL cache with per-key stampede protection."""

    def __init__(
        self,
        ttl_seconds: float,
        max_size: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._clock = clock
        self._entries: dict[KeyT, _CacheEntry[ValueT]] = {}
        self._locks: dict[KeyT, asyncio.Lock] = {}

    async def get_or_load(
        self,
        key: KeyT,
        loader: Callable[[], Awaitable[ValueT]],
    ) -> ValueT:
        self._purge_expired()
        cached = self._fresh_entry(key)
        if cached is not None:
            return cached.value

        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                cached = self._fresh_entry(key)
                if cached is not None:
                    return cached.value
                value = await loader()
                self._evict_if_full(key)
                self._entries[key] = _CacheEntry(
                    value=value,
                    expires_at=self._clock() + self._ttl_seconds,
                )
                return value
        finally:
            if key not in self._entries and self._locks.get(key) is lock and not lock.locked():
                self._locks.pop(key, None)

    def invalidate(self, key: KeyT) -> None:
        self._entries.pop(key, None)
        lock = self._locks.get(key)
        if lock is not None and not lock.locked():
            self._locks.pop(key, None)

    def _fresh_entry(self, key: KeyT) -> _CacheEntry[ValueT] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._entries.pop(key, None)
            return None
        return entry

    def _purge_expired(self) -> None:
        now = self._clock()
        expired_keys = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired_keys:
            self.invalidate(key)

    def _evict_if_full(self, incoming_key: KeyT) -> None:
        if incoming_key in self._entries or len(self._entries) < self._max_size:
            return
        oldest_key = min(self._entries, key=lambda key: self._entries[key].expires_at)
        self.invalidate(oldest_key)
