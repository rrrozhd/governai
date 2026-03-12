from __future__ import annotations

import asyncio
import inspect
from abc import ABC, abstractmethod
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from typing import Any, Callable, Iterable, Sequence, TypeVar


T = TypeVar("T")
R = TypeVar("R")


def _run_maybe_awaitable_sync(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Internal helper to run maybe awaitable sync."""
    value = func(*args, **kwargs)
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


class ExecutionBackend(ABC):
    """Transport-agnostic execution backend for governed local concurrency."""

    @abstractmethod
    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run one callable and return its result."""

    async def parallel(self, callables: Sequence[Callable[[], Any]]) -> list[Any]:
        """Run callables in parallel and preserve input order."""
        tasks = [asyncio.create_task(self.call(fn)) for fn in callables]
        return list(await asyncio.gather(*tasks))

    async def amap(self, func: Callable[[T], Any], items: Iterable[T]) -> list[Any]:
        """Map a callable over items concurrently with deterministic order."""
        return await self.parallel([partial(func, item) for item in items])

    def fan_in(self, results: Sequence[Any], *, reducer: Callable[[Sequence[Any]], R] | None = None) -> Any:
        """Deterministic fan-in merge helper."""
        if reducer is not None:
            return reducer(results)
        return list(results)


class AsyncBackend(ExecutionBackend):
    """Default backend that runs everything on the current event loop."""

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call."""
        value = func(*args, **kwargs)
        if inspect.isawaitable(value):
            return await value
        return value


class ThreadPoolBackend(ExecutionBackend):
    """Backend that runs each invocation in a worker thread."""

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call."""
        return await asyncio.to_thread(_run_maybe_awaitable_sync, func, *args, **kwargs)


class ProcessPoolBackend(ExecutionBackend):
    """Backend that runs sync callables in a process pool."""

    def __init__(self, *, max_workers: int | None = None) -> None:
        """Initialize ProcessPoolBackend."""
        self._pool = ProcessPoolExecutor(max_workers=max_workers)

    async def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Call."""
        if inspect.iscoroutinefunction(func):
            raise TypeError("ProcessPoolBackend only supports sync callables")
        loop = asyncio.get_running_loop()
        bound = partial(func, *args, **kwargs)
        return await loop.run_in_executor(self._pool, bound)

    async def aclose(self) -> None:
        """Aclose."""
        self._pool.shutdown(wait=False, cancel_futures=True)
