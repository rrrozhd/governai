from __future__ import annotations

from governai.runtime.interrupts import InterruptManager


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
