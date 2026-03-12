from __future__ import annotations

from functools import partial
from typing import Any, Callable, Iterable, Sequence, TypeVar

from governai.execution.backends import AsyncBackend, ExecutionBackend


T = TypeVar("T")
R = TypeVar("R")
_DEFAULT_BACKEND: ExecutionBackend = AsyncBackend()


def get_default_backend() -> ExecutionBackend:
    """Get default backend."""
    return _DEFAULT_BACKEND


def set_default_backend(backend: ExecutionBackend) -> None:
    """Set default backend."""
    global _DEFAULT_BACKEND
    _DEFAULT_BACKEND = backend


async def call(func: Callable[..., Any], *args: Any, backend: ExecutionBackend | None = None, **kwargs: Any) -> Any:
    """Execute one callable through the selected backend."""
    runner = backend or _DEFAULT_BACKEND
    return await runner.call(func, *args, **kwargs)


async def parallel(
    callables: Sequence[Callable[[], Any]], *, backend: ExecutionBackend | None = None
) -> list[Any]:
    """Execute many callables concurrently and preserve deterministic order."""
    runner = backend or _DEFAULT_BACKEND
    return await runner.parallel(callables)


async def amap(
    func: Callable[[T], Any], items: Iterable[T], *, backend: ExecutionBackend | None = None
) -> list[Any]:
    """Map over iterable items using backend concurrency."""
    runner = backend or _DEFAULT_BACKEND
    return await runner.parallel([partial(func, item) for item in items])


def fan_in(
    results: Sequence[Any],
    *,
    backend: ExecutionBackend | None = None,
    reducer: Callable[[Sequence[Any]], R] | None = None,
) -> Any:
    """Deterministic result merge for fan-in points."""
    runner = backend or _DEFAULT_BACKEND
    return runner.fan_in(results, reducer=reducer)
