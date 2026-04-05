from __future__ import annotations

import inspect
import time

import pytest

from governai.runtime.interrupts import InMemoryInterruptStore, InterruptManager, InterruptRequest, InterruptStore
from governai.runtime.interrupts import RedisInterruptStore
from governai.workflows.exceptions import InterruptExpiredError


class FakeSyncRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    def set(self, key: str, value: str) -> None:
        self.data[key] = value

    def get(self, key: str):
        return self.data.get(key)

    def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.lists.pop(key, None)

    def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    def lrange(self, key: str, start: int, stop: int):  # noqa: ARG002
        values = self.lists.get(key, [])
        if stop == -1:
            stop = len(values) - 1
        return values[start : stop + 1]

    def close(self) -> None:
        return None


def test_interrupt_create_list_resolve() -> None:
    mgr = InterruptManager(default_ttl_seconds=60)
    req = mgr.create(run_id="r1", step_name="s1", message="Need input")

    pending = mgr.list_pending("r1")
    assert len(pending) == 1
    assert pending[0].interrupt_id == req.interrupt_id

    resolution = mgr.resolve(run_id="r1", interrupt_id=req.interrupt_id, response="ok")
    assert resolution.response == "ok"
    assert mgr.list_pending("r1") == []


def test_interrupt_epoch_guard() -> None:
    mgr = InterruptManager(default_ttl_seconds=60)
    epoch = mgr.bump_epoch("r2")
    req = mgr.create(run_id="r2", step_name="s1", message="Need input", epoch=epoch)

    try:
        mgr.resolve(run_id="r2", interrupt_id=req.interrupt_id, response="ok", epoch=epoch + 1)
    except ValueError as exc:
        assert "epoch mismatch" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected epoch mismatch error")


def test_interrupt_expiration_cleanup() -> None:
    mgr = InterruptManager(default_ttl_seconds=60)
    req = mgr.create(run_id="r3", step_name="s1", message="Need input")
    req.expires_at = req.created_at - 1

    pending = mgr.list_pending("r3")
    assert pending == []
    removed = mgr.clear_expired("r3")
    assert removed == 1


def test_interrupt_max_pending_enforced() -> None:
    mgr = InterruptManager(default_ttl_seconds=60)
    mgr.create(run_id="r4", step_name="s1", message="one", max_pending=1)
    try:
        mgr.create(run_id="r4", step_name="s1", message="two", max_pending=1)
    except ValueError as exc:
        assert "max pending" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected max pending enforcement")


def test_redis_interrupt_store_persists_requests_and_epochs() -> None:
    fake = FakeSyncRedis()
    mgr_a = InterruptManager(
        default_ttl_seconds=60,
        store=RedisInterruptStore(redis_url="redis://unused", redis_client=fake),
    )
    epoch = mgr_a.bump_epoch("redis-run")
    req = mgr_a.create(run_id="redis-run", step_name="s1", message="Need input", epoch=epoch)

    mgr_b = InterruptManager(
        default_ttl_seconds=60,
        store=RedisInterruptStore(redis_url="redis://unused", redis_client=fake),
    )
    assert mgr_b.current_epoch("redis-run") == epoch
    pending = mgr_b.list_pending("redis-run", epoch=epoch)
    assert len(pending) == 1
    assert pending[0].interrupt_id == req.interrupt_id
    resolution = mgr_b.resolve(
        run_id="redis-run",
        interrupt_id=req.interrupt_id,
        response={"ok": True},
        epoch=epoch,
    )
    assert resolution.response == {"ok": True}
    assert mgr_b.list_pending("redis-run") == []


def test_redis_interrupt_store_preserves_expired_and_epoch_mismatch_behavior() -> None:
    fake = FakeSyncRedis()
    mgr_a = InterruptManager(
        default_ttl_seconds=60,
        store=RedisInterruptStore(redis_url="redis://unused", redis_client=fake),
    )
    epoch = mgr_a.bump_epoch("redis-expired")
    req = mgr_a.create(run_id="redis-expired", step_name="s1", message="Need input", epoch=epoch, ttl_seconds=0)

    mgr_b = InterruptManager(
        default_ttl_seconds=60,
        store=RedisInterruptStore(redis_url="redis://unused", redis_client=fake),
    )
    with pytest.raises(ValueError, match="expired"):
        mgr_b.resolve(run_id="redis-expired", interrupt_id=req.interrupt_id, response="late", epoch=epoch)

    req2 = mgr_b.create(run_id="redis-expired", step_name="s2", message="Need input", epoch=mgr_b.bump_epoch("redis-expired"))
    with pytest.raises(ValueError, match="epoch mismatch"):
        mgr_b.resolve(run_id="redis-expired", interrupt_id=req2.interrupt_id, response="nope", epoch=req2.epoch + 1)


# --- NEW TESTS: Async migration, InterruptExpiredError, sweep_expired ---


@pytest.mark.asyncio
async def test_resolve_expired_raises_interrupt_expired_error() -> None:
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


@pytest.mark.asyncio
async def test_interrupt_expired_error_carries_request() -> None:
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


@pytest.mark.asyncio
async def test_sweep_expired_removes_global() -> None:
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


@pytest.mark.asyncio
async def test_sweep_expired_returns_zero_when_none_expired() -> None:
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
