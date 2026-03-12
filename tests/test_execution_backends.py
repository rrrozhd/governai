from __future__ import annotations

import asyncio

import pytest

from governai.execution import AsyncBackend, ProcessPoolBackend, ThreadPoolBackend, fan_in, parallel


def test_async_backend_call_sync_and_async() -> None:
    async def run() -> None:
        backend = AsyncBackend()

        def sync_fn(value: int) -> int:
            return value + 1

        async def async_fn(value: int) -> int:
            return value + 2

        assert await backend.call(sync_fn, 1) == 2
        assert await backend.call(async_fn, 1) == 3

    asyncio.run(run())


def test_thread_backend_supports_async_callable() -> None:
    async def run() -> None:
        backend = ThreadPoolBackend()

        async def async_fn(value: int) -> int:
            return value * 2

        assert await backend.call(async_fn, 5) == 10

    asyncio.run(run())


def test_process_backend_rejects_coroutine_function() -> None:
    async def run() -> None:
        backend = ProcessPoolBackend(max_workers=1)

        async def async_fn() -> int:
            return 1

        with pytest.raises(TypeError):
            await backend.call(async_fn)
        await backend.aclose()

    asyncio.run(run())


def test_parallel_preserves_order_and_fan_in_is_deterministic() -> None:
    async def run() -> None:
        values = await parallel(
            [
                lambda: 3,
                lambda: 1,
                lambda: 2,
            ]
        )
        assert values == [3, 1, 2]
        merged = fan_in(values, reducer=lambda xs: ":".join(str(x) for x in xs))
        assert merged == "3:1:2"

    asyncio.run(run())
