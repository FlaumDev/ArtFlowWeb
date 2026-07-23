from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any, Generic, TypeVar


Key = TypeVar("Key")
Value = TypeVar("Value")


class AsyncTTLCache(Generic[Key, Value]):
    """Small process-local TTL cache with bounded storage and async locking."""

    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        if ttl_seconds <= 0 or max_entries <= 0:
            raise ValueError("Cache TTL and size must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._items: OrderedDict[Key, tuple[float, Value]] = OrderedDict()
        self._inflight: dict[Key, asyncio.Future[Value]] = {}
        self._lock = asyncio.Lock()

    async def get_or_load(
        self,
        key: Key,
        loader: Callable[[], Awaitable[Value]],
    ) -> Value:
        should_load = False
        async with self._lock:
            now = time.monotonic()
            cached = self._items.get(key)
            if cached is not None:
                expires_at, value = cached
                if expires_at > now:
                    self._items.move_to_end(key)
                    return value
                del self._items[key]

            pending = self._inflight.get(key)
            if pending is None:
                pending = asyncio.get_running_loop().create_future()
                self._inflight[key] = pending
                should_load = True

        if not should_load:
            return await asyncio.shield(pending)

        try:
            value = await loader()
        except BaseException as error:
            async with self._lock:
                if self._inflight.get(key) is pending:
                    del self._inflight[key]
                if not pending.done():
                    pending.set_exception(error)
                    pending.exception()
            raise

        async with self._lock:
            if self._inflight.get(key) is pending:
                del self._inflight[key]
                self._items[key] = (
                    time.monotonic() + self.ttl_seconds,
                    value,
                )
                self._items.move_to_end(key)
                while len(self._items) > self.max_entries:
                    self._items.popitem(last=False)
                pending.set_result(value)
        return value

    def clear(self) -> None:
        self._items.clear()


class ApplicationCaches:
    """Per-application caches so FastAPI instances never share runtime data."""

    def __init__(
        self,
        *,
        public_ttl_seconds: float = 30,
        health_ttl_seconds: float = 5,
    ) -> None:
        self.competitions: AsyncTTLCache[
            tuple[Any, ...], list[dict[str, Any]]
        ] = AsyncTTLCache(
            ttl_seconds=public_ttl_seconds,
            max_entries=8,
        )
        self.competition_details: AsyncTTLCache[
            int, dict[str, Any] | None
        ] = AsyncTTLCache(
            ttl_seconds=public_ttl_seconds,
            max_entries=64,
        )
        self.faq: AsyncTTLCache[str, list[dict[str, Any]]] = AsyncTTLCache(
            ttl_seconds=public_ttl_seconds,
            max_entries=2,
        )
        self.health_db: AsyncTTLCache[str, bool] = AsyncTTLCache(
            ttl_seconds=health_ttl_seconds,
            max_entries=1,
        )

    def clear(self) -> None:
        self.competitions.clear()
        self.competition_details.clear()
        self.faq.clear()
        self.health_db.clear()
