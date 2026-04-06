from __future__ import annotations

import asyncio
import inspect
import time

import pytest

from governai.runtime.interrupts import InMemoryInterruptStore, InterruptManager, InterruptRequest, InterruptStore
from governai.runtime.interrupts import RedisInterruptStore
from governai.workflows.exceptions import InterruptExpiredError


class AsyncFakeRedis:
    """Async fake redis client for testing RedisInterruptStore."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self.data[key] = value

    async def get(self, key: str):
        return self.data.get(key)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.lists.pop(key, None)

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def lrange(self, key: str, start: int, stop: int):  # noqa: ARG002
        values = self.lists.get(key, [])
        if stop == -1:
            stop = len(values) - 1
        return values[start : stop + 1]

    async def scan(self, cursor: int, match: str | None = None, count: int | None = None) -> tuple[int, list[str]]:  # noqa: ARG002
        """Simulate Redis SCAN over self.data keys matching a glob pattern."""
        import fnmatch

        matched = [k for k in self.data if match is None or fnmatch.fnmatch(k, match)]
        return (0, matched)

    async def aclose(self) -> None:
        return None


def test_interrupt_create_list_resolve() -> None:
    async def run() -> None:
        mgr = InterruptManager(default_ttl_seconds=60)
        req = await mgr.create(run_id="r1", step_name="s1", message="Need input")

        pending = await mgr.list_pending("r1")
        assert len(pending) == 1
        assert pending[0].interrupt_id == req.interrupt_id

        resolution = await mgr.resolve(run_id="r1", interrupt_id=req.interrupt_id, response="ok")
        assert resolution.response == "ok"
        assert await mgr.list_pending("r1") == []

    asyncio.run(run())


def test_interrupt_epoch_guard() -> None:
    async def run() -> None:
        mgr = InterruptManager(default_ttl_seconds=60)
        epoch = await mgr.bump_epoch("r2")
        req = await mgr.create(run_id="r2", step_name="s1", message="Need input", epoch=epoch)

        try:
            await mgr.resolve(run_id="r2", interrupt_id=req.interrupt_id, response="ok", epoch=epoch + 1)
        except ValueError as exc:
            assert "epoch mismatch" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("Expected epoch mismatch error")

    asyncio.run(run())


def test_interrupt_expiration_cleanup() -> None:
    async def run() -> None:
        mgr = InterruptManager(default_ttl_seconds=60)
        req = await mgr.create(run_id="r3", step_name="s1", message="Need input")
        req.expires_at = req.created_at - 1

        pending = await mgr.list_pending("r3")
        assert pending == []
        removed = await mgr.clear_expired("r3")
        assert removed == 1

    asyncio.run(run())


def test_interrupt_max_pending_enforced() -> None:
    async def run() -> None:
        mgr = InterruptManager(default_ttl_seconds=60)
        await mgr.create(run_id="r4", step_name="s1", message="one", max_pending=1)
        try:
            await mgr.create(run_id="r4", step_name="s1", message="two", max_pending=1)
        except ValueError as exc:
            assert "max pending" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("Expected max pending enforcement")

    asyncio.run(run())


def test_redis_interrupt_store_persists_requests_and_epochs() -> None:
    async def run() -> None:
        fake = AsyncFakeRedis()
        mgr_a = InterruptManager(
            default_ttl_seconds=60,
            store=RedisInterruptStore(redis_url="redis://unused", redis_client=fake),
        )
        epoch = await mgr_a.bump_epoch("redis-run")
        req = await mgr_a.create(run_id="redis-run", step_name="s1", message="Need input", epoch=epoch)

        mgr_b = InterruptManager(
            default_ttl_seconds=60,
            store=RedisInterruptStore(redis_url="redis://unused", redis_client=fake),
        )
        assert await mgr_b.current_epoch("redis-run") == epoch
        pending = await mgr_b.list_pending("redis-run", epoch=epoch)
        assert len(pending) == 1
        assert pending[0].interrupt_id == req.interrupt_id
        resolution = await mgr_b.resolve(
            run_id="redis-run",
            interrupt_id=req.interrupt_id,
            response={"ok": True},
            epoch=epoch,
        )
        assert resolution.response == {"ok": True}
        assert await mgr_b.list_pending("redis-run") == []

    asyncio.run(run())


def test_redis_interrupt_store_preserves_expired_and_epoch_mismatch_behavior() -> None:
    async def run() -> None:
        fake = AsyncFakeRedis()
        mgr_a = InterruptManager(
            default_ttl_seconds=60,
            store=RedisInterruptStore(redis_url="redis://unused", redis_client=fake),
        )
        epoch = await mgr_a.bump_epoch("redis-expired")
        req = await mgr_a.create(run_id="redis-expired", step_name="s1", message="Need input", epoch=epoch, ttl_seconds=0)

        mgr_b = InterruptManager(
            default_ttl_seconds=60,
            store=RedisInterruptStore(redis_url="redis://unused", redis_client=fake),
        )
        with pytest.raises(InterruptExpiredError, match="expired"):
            await mgr_b.resolve(run_id="redis-expired", interrupt_id=req.interrupt_id, response="late", epoch=epoch)

        req2 = await mgr_b.create(run_id="redis-expired", step_name="s2", message="Need input", epoch=await mgr_b.bump_epoch("redis-expired"))
        with pytest.raises(ValueError, match="epoch mismatch"):
            await mgr_b.resolve(run_id="redis-expired", interrupt_id=req2.interrupt_id, response="nope", epoch=req2.epoch + 1)

    asyncio.run(run())


# --- Async migration, InterruptExpiredError, sweep_expired ---


def test_resolve_expired_raises_interrupt_expired_error() -> None:
    async def run() -> None:
        store = InMemoryInterruptStore()
        mgr = InterruptManager(default_ttl_seconds=60, store=store)
        req = InterruptRequest(
            interrupt_id="exp-1",
            run_id="r-exp",
            step_name="s1",
            message="test",
            epoch=1,
            created_at=int(time.time()) - 200,
            expires_at=int(time.time()) - 100,
            status="pending",
        )
        await store.save_request(req)
        await store.set_epoch("r-exp", 1)

        with pytest.raises(InterruptExpiredError) as exc_info:
            await mgr.resolve(run_id="r-exp", interrupt_id="exp-1", response="yes")
        assert exc_info.value.request.interrupt_id == "exp-1"

    asyncio.run(run())


def test_interrupt_expired_error_carries_request() -> None:
    async def run() -> None:
        store = InMemoryInterruptStore()
        mgr = InterruptManager(default_ttl_seconds=60, store=store)
        now = int(time.time())
        req = InterruptRequest(
            interrupt_id="exp-2",
            run_id="r-exp2",
            step_name="s1",
            message="test",
            epoch=1,
            created_at=now - 200,
            expires_at=now - 50,
            status="pending",
        )
        await store.save_request(req)
        await store.set_epoch("r-exp2", 1)

        with pytest.raises(InterruptExpiredError) as exc_info:
            await mgr.resolve(run_id="r-exp2", interrupt_id="exp-2", response="yes")
        assert exc_info.value.request.expires_at < now
        assert exc_info.value.request.status == "expired"

    asyncio.run(run())


def test_sweep_expired_removes_global() -> None:
    async def run() -> None:
        store = InMemoryInterruptStore()
        now = int(time.time())
        # 3 expired across 3 different runs
        for i, run_id in enumerate(["run-a", "run-b", "run-c"]):
            req = InterruptRequest(
                interrupt_id=f"exp-{i}",
                run_id=run_id,
                step_name="s1",
                message="test",
                epoch=1,
                created_at=now - 200,
                expires_at=now - 100,
                status="pending",
            )
            await store.save_request(req)
        # 2 non-expired
        for i, run_id in enumerate(["run-a", "run-d"]):
            req = InterruptRequest(
                interrupt_id=f"fresh-{i}",
                run_id=run_id,
                step_name="s1",
                message="test",
                epoch=1,
                created_at=now,
                expires_at=now + 3600,
                status="pending",
            )
            await store.save_request(req)

        count = await store.sweep_expired()
        assert count == 3

        # Remaining should be 2
        remaining = 0
        for run_id in ["run-a", "run-b", "run-c", "run-d"]:
            remaining += len(await store.list_requests(run_id))
        assert remaining == 2

    asyncio.run(run())


def test_sweep_expired_returns_zero_when_none_expired() -> None:
    async def run() -> None:
        store = InMemoryInterruptStore()
        now = int(time.time())
        req = InterruptRequest(
            interrupt_id="fresh-only",
            run_id="run-fresh",
            step_name="s1",
            message="test",
            epoch=1,
            created_at=now,
            expires_at=now + 3600,
            status="pending",
        )
        await store.save_request(req)
        count = await store.sweep_expired()
        assert count == 0

    asyncio.run(run())


def test_interrupt_store_methods_are_async() -> None:
    methods = [
        "get_epoch", "set_epoch", "save_request",
        "get_request", "list_requests", "delete_request",
        "sweep_expired",
    ]
    for name in methods:
        method = getattr(InMemoryInterruptStore, name)
        assert inspect.iscoroutinefunction(method), f"{name} should be async"


def test_interrupt_manager_methods_are_async() -> None:
    methods = [
        "resolve", "create", "list_pending",
        "get_pending", "bump_epoch", "current_epoch",
    ]
    for name in methods:
        method = getattr(InterruptManager, name)
        assert inspect.iscoroutinefunction(method), f"{name} should be async"
