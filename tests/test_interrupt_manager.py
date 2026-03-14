from __future__ import annotations

import pytest

from governai.runtime.interrupts import InterruptManager
from governai.runtime.interrupts import RedisInterruptStore


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
