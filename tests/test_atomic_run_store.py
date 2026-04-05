"""Tests for atomic run store operations: WATCH/MULTI/EXEC, epoch CAS, state validation."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from governai.models.common import RunStatus
from governai.models.run_state import RunState
from governai.runtime.run_store import (
    InMemoryRunStore,
    RedisRunStore,
    StateConcurrencyError,
    _validate_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(
    run_id: str = "run-1",
    *,
    thread_id: str = "thread-1",
    status: RunStatus = RunStatus.RUNNING,
    epoch: int = 0,
    pending_interrupt_id: str | None = None,
    pending_approval: Any = None,
) -> RunState:
    return RunState(
        run_id=run_id,
        thread_id=thread_id,
        workflow_name="TestWF",
        status=status,
        current_step="s1",
        epoch=epoch,
        pending_interrupt_id=pending_interrupt_id,
        pending_approval=pending_approval,
    )


# ---------------------------------------------------------------------------
# TransactionalFakeRedis — extends FakeRedis with pipeline support
# ---------------------------------------------------------------------------

class FakePipeline:
    """Fake async Redis pipeline supporting watch/multi/execute."""

    def __init__(self, parent: "TransactionalFakeRedis") -> None:
        self._parent = parent
        self._watched_keys: list[str] = []
        self._watched_values: dict[str, str | None] = {}
        self._in_multi = False
        self._commands: list[tuple[str, tuple]] = []

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, *args: Any) -> None:
        self._watched_keys.clear()
        self._watched_values.clear()
        self._in_multi = False
        self._commands.clear()

    async def watch(self, *keys: str) -> None:
        for key in keys:
            self._watched_keys.append(key)
            self._watched_values[key] = self._parent.data.get(key)

    async def get(self, key: str) -> str | None:
        """Immediate-mode read (before multi)."""
        return self._parent.data.get(key)

    def multi(self) -> None:
        self._in_multi = True
        self._parent._multi_called = True

    def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self._commands.append(("set", (key, value)))

    def rpush(self, key: str, value: str) -> None:
        self._commands.append(("rpush", (key, value)))

    async def execute(self) -> list[Any]:
        # Simulate WatchError injection
        if self._parent._force_watch_error > 0:
            self._parent._force_watch_error -= 1
            self._parent._watch_called = True
            self._parent._execute_called = True
            # Import here so the test can verify the real exception type
            try:
                from redis.exceptions import WatchError
            except ImportError:
                # Fallback: create a compatible exception
                class WatchError(Exception):  # type: ignore[no-redef]
                    pass
            raise WatchError("Simulated watch conflict")

        # Check watched keys for changes
        for key in self._watched_keys:
            current = self._parent.data.get(key)
            if current != self._watched_values.get(key):
                try:
                    from redis.exceptions import WatchError
                except ImportError:
                    class WatchError(Exception):  # type: ignore[no-redef]
                        pass
                raise WatchError("Watched key changed")

        # Execute buffered commands
        results: list[Any] = []
        for cmd, args in self._commands:
            if cmd == "set":
                self._parent.data[args[0]] = args[1]
                results.append(True)
            elif cmd == "rpush":
                self._parent.lists.setdefault(args[0], []).append(args[1])
                results.append(len(self._parent.lists[args[0]]))
        self._parent._execute_called = True
        return results


class TransactionalFakeRedis:
    """FakeRedis with pipeline/watch/multi/execute support for testing atomic writes."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self._force_watch_error: int = 0
        self._watch_called: bool = False
        self._multi_called: bool = False
        self._execute_called: bool = False

    async def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self.data[key] = value

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)
        self.lists.pop(key, None)

    async def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)

    async def lindex(self, key: str, idx: int) -> str | None:
        values = self.lists.get(key, [])
        if not values:
            return None
        return values[idx]

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        values = self.lists.get(key, [])
        if stop == -1:
            stop = len(values) - 1
        return values[start : stop + 1]

    async def expire(self, key: str, seconds: int) -> None:  # noqa: ARG002
        return None

    async def aclose(self) -> None:
        return None

    def pipeline(self, transaction: bool = True) -> FakePipeline:  # noqa: ARG002
        return FakePipeline(self)


# ---------------------------------------------------------------------------
# Tests: StateConcurrencyError
# ---------------------------------------------------------------------------

def test_state_concurrency_error_is_runtime_error() -> None:
    assert issubclass(StateConcurrencyError, RuntimeError)
    exc = StateConcurrencyError("conflict")
    assert isinstance(exc, RuntimeError)


# ---------------------------------------------------------------------------
# Tests: _validate_state
# ---------------------------------------------------------------------------

def test_validate_state_rejects_waiting_interrupt_without_id() -> None:
    state = _state(status=RunStatus.WAITING_INTERRUPT, pending_interrupt_id=None)
    with pytest.raises(ValueError, match="WAITING_INTERRUPT"):
        _validate_state(state)


def test_validate_state_rejects_waiting_approval_without_request() -> None:
    state = _state(status=RunStatus.WAITING_APPROVAL, pending_approval=None)
    with pytest.raises(ValueError, match="WAITING_APPROVAL"):
        _validate_state(state)


def test_validate_state_accepts_valid_state() -> None:
    state = _state(status=RunStatus.RUNNING)
    _validate_state(state)  # Should not raise


# ---------------------------------------------------------------------------
# Tests: InMemoryRunStore epoch-based CAS
# ---------------------------------------------------------------------------

def test_inmemory_put_rejects_stale_epoch() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        s = _state("r1", epoch=0)
        await store.put(s)  # epoch becomes 1

        stale = _state("r1", epoch=1)
        # Store has epoch=1, stale write also epoch=1 => store.epoch >= write.epoch => reject
        with pytest.raises(StateConcurrencyError, match="Stale write"):
            await store.put(stale)

    asyncio.run(run())


def test_inmemory_put_auto_increments_epoch() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        s = _state("r1", epoch=0)
        await store.put(s)
        loaded = await store.get("r1")
        assert loaded is not None
        assert loaded.epoch == 1

        # Put again with fresh epoch
        s2 = _state("r1", epoch=1)
        # epoch=1 is not stale because existing.epoch=1 >= write.epoch=1 => stale
        # So we need epoch > existing to succeed... but the plan says
        # put(state with epoch=1) after get()->epoch=1 should succeed
        # Actually: existing.epoch(1) >= state.epoch(1) => stale. Hmm.
        # Re-reading plan: "put(state with epoch=1) -> get() -> epoch=2"
        # This means existing.epoch=1, write.epoch=1 => should REJECT?
        # Wait no: the test says "put again with epoch=1 -> get() -> epoch=2"
        # That implies epoch=1 is stale but wait... Let me re-read the plan.
        # "put(state with epoch=0), then get() -> epoch=1;
        #  put again with epoch=1 -> get() -> epoch=2 (auto-increment inside put)"
        # So epoch=1 write against stored epoch=1 should... succeed?
        # The condition is: existing.epoch >= state.epoch => reject.
        # 1 >= 1 is true => reject. But the plan test says it succeeds.
        # Let me check: the plan says "existing is not None and existing.epoch >= state.epoch"
        # Wait, the plan action code says:
        #   if existing is not None and existing.epoch >= state.epoch:
        #       raise StateConcurrencyError
        # But then test says put(epoch=1) after epoch=1 should succeed -> contradiction.
        # The plan behavior says: "put again with epoch=1 -> get() -> epoch=2"
        # This implies the check should be: existing.epoch > state.epoch (strictly greater)
        # NOT >=. Let me look at the stale test: "store has state at epoch=2,
        # put(state with epoch=1) raises StateConcurrencyError"
        # epoch=2 > epoch=1 => stale. Makes sense with strict >.
        # But with >=: epoch=2 >= 1 also works.
        # The auto-increment test: existing epoch=1, write epoch=1:
        #   With >: 1 > 1 is false => accepts. Good.
        #   With >=: 1 >= 1 is true => rejects. Bad.
        # So the condition must be strictly >. I'll implement accordingly.
        s2 = _state("r1", epoch=1)
        await store.put(s2)
        loaded2 = await store.get("r1")
        assert loaded2 is not None
        assert loaded2.epoch == 2

    asyncio.run(run())


def test_inmemory_put_accepts_fresh_write() -> None:
    async def run() -> None:
        store = InMemoryRunStore()
        s = _state("r1", epoch=0)
        await store.put(s)  # Should succeed — no existing state
        loaded = await store.get("r1")
        assert loaded is not None
        assert loaded.epoch == 1

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Tests: RedisRunStore atomic writes
# ---------------------------------------------------------------------------

def test_redis_put_atomic_write() -> None:
    async def run() -> None:
        fake = TransactionalFakeRedis()
        store = RedisRunStore(redis_url="redis://unused", redis_client=fake)
        s = _state("r1")
        await store.put(s)
        assert fake._multi_called, "pipeline.multi() was not called"
        assert fake._execute_called, "pipeline.execute() was not called"

    asyncio.run(run())


def test_redis_put_retries_on_watch_error() -> None:
    async def run() -> None:
        fake = TransactionalFakeRedis()
        fake._force_watch_error = 1  # Fail first attempt, succeed second
        store = RedisRunStore(redis_url="redis://unused", redis_client=fake)
        s = _state("r1")
        await store.put(s)
        loaded = await store.get("r1")
        assert loaded is not None

    asyncio.run(run())


def test_redis_put_raises_after_max_retries() -> None:
    async def run() -> None:
        fake = TransactionalFakeRedis()
        fake._force_watch_error = 10  # More than max retries
        store = RedisRunStore(redis_url="redis://unused", redis_client=fake)
        s = _state("r1")
        with pytest.raises(StateConcurrencyError, match="retries"):
            await store.put(s)

    asyncio.run(run())


def test_redis_put_validates_before_write() -> None:
    async def run() -> None:
        fake = TransactionalFakeRedis()
        store = RedisRunStore(redis_url="redis://unused", redis_client=fake)
        s = _state("r1", status=RunStatus.WAITING_INTERRUPT, pending_interrupt_id=None)
        with pytest.raises(ValueError, match="WAITING_INTERRUPT"):
            await store.put(s)
        # Should not have touched Redis at all
        assert not fake._execute_called

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Tests: v0.2.2 fixture deserialization
# ---------------------------------------------------------------------------

def test_v022_fixture_deserializes() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "run_state_v022.json"
    raw = fixture_path.read_text()
    state = RunState.model_validate_json(raw)
    assert state.run_id == "run-v022-fixture"
    assert state.workflow_name == "LegacyWorkflow"
    assert state.status == RunStatus.RUNNING
    assert state.metadata == {"source": "v0.2.2-test"}
    # Unknown field should be silently ignored
    data = json.loads(raw)
    assert "some_future_field" in data
