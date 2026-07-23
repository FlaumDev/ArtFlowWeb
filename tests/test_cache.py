import asyncio

import pytest

from app.cache import ApplicationCaches, AsyncTTLCache
from app.main import create_app


def test_concurrent_cache_miss_runs_loader_once():
    cache = AsyncTTLCache[str, int](ttl_seconds=30, max_entries=2)
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return 7

    async def load_concurrently():
        return await asyncio.gather(
            *(cache.get_or_load("same-key", loader) for _ in range(10))
        )

    assert asyncio.run(load_concurrently()) == [7] * 10
    assert calls == 1


def test_different_cache_keys_load_concurrently():
    cache = AsyncTTLCache[str, int](ttl_seconds=30, max_entries=2)

    async def load_concurrently():
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release = asyncio.Event()

        async def loader(started: asyncio.Event, value: int) -> int:
            started.set()
            await release.wait()
            return value

        first = asyncio.create_task(
            cache.get_or_load("first", lambda: loader(first_started, 1))
        )
        await first_started.wait()
        second = asyncio.create_task(
            cache.get_or_load("second", lambda: loader(second_started, 2))
        )
        await asyncio.wait_for(second_started.wait(), timeout=1)
        release.set()
        return await asyncio.gather(first, second)

    assert asyncio.run(load_concurrently()) == [1, 2]


def test_loader_error_is_not_cached():
    cache = AsyncTTLCache[str, int](ttl_seconds=30, max_entries=2)
    calls = 0

    async def failing_loader() -> int:
        nonlocal calls
        calls += 1
        raise RuntimeError("controlled cache loader failure")

    async def load_twice():
        for _ in range(2):
            with pytest.raises(RuntimeError, match="controlled cache loader failure"):
                await cache.get_or_load("failure", failing_loader)

    asyncio.run(load_twice())
    assert calls == 2


def test_application_cache_is_bounded_and_clearable():
    caches = ApplicationCaches(public_ttl_seconds=30)

    async def fill_cache():
        for item in range(70):
            await caches.competition_details.get_or_load(
                item,
                lambda item=item: _value(item),
            )

    async def _value(value):
        return {"id": value}

    asyncio.run(fill_cache())
    assert len(caches.competition_details._items) == 64
    caches.clear()
    assert not caches.competition_details._items


def test_fastapi_instances_do_not_share_caches():
    first = create_app()
    second = create_app()
    assert first.state.caches is not second.state.caches
