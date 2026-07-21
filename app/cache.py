from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar


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
        self._lock = asyncio.Lock()

    async def get_or_load(
        self,
        key: Key,
        loader: Callable[[], Awaitable[Value]],
    ) -> Value:
        async with self._lock:
            now = time.monotonic()
            cached = self._items.get(key)
            if cached is not None:
                expires_at, value = cached
                if expires_at > now:
                    self._items.move_to_end(key)
                    return value
                del self._items[key]

            # Exceptions deliberately escape before a value can be cached.
            value = await loader()
            self._items[key] = (time.monotonic() + self.ttl_seconds, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
            return value

    def clear(self) -> None:
        self._items.clear()
