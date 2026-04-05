from __future__ import annotations

import asyncio
import copy
from datetime import datetime

from governai.runtime.thread_store import (
    InMemoryThreadStore,
    ThreadRecord,
    ThreadStatus,
    ThreadStore,
    ThreadTransitionError,
)


# ---------------------------------------------------------------------------
# ThreadStatus
# ---------------------------------------------------------------------------


def test_thread_status_values() -> None:
    values = {s.value for s in ThreadStatus}
    assert values == {"created", "active", "interrupted", "idle", "archived"}
    assert len(list(ThreadStatus)) == 5


# ---------------------------------------------------------------------------
# ThreadRecord defaults
# ---------------------------------------------------------------------------


def test_thread_record_defaults() -> None:
    record = ThreadRecord(thread_id="t1")
    assert record.thread_id == "t1"
    assert record.status == ThreadStatus.CREATED
    assert record.run_ids == []
    assert isinstance(record.created_at, datetime)
    assert isinstance(record.updated_at, datetime)
    assert record.metadata == {}


def test_thread_record_model_roundtrip() -> None:
    record = ThreadRecord(thread_id="t1")
    json_str = record.model_dump_json()
    restored = ThreadRecord.model_validate_json(json_str)
    assert restored.thread_id == record.thread_id
    assert restored.status == record.status
    assert restored.run_ids == record.run_ids
    assert restored.created_at == record.created_at
    assert restored.updated_at == record.updated_at
    assert restored.metadata == record.metadata


# ---------------------------------------------------------------------------
# InMemoryThreadStore — create / get
# ---------------------------------------------------------------------------


def test_create_thread() -> None:
    store = InMemoryThreadStore()
    record = asyncio.run(store.create("t1"))
    assert record.thread_id == "t1"
    assert record.status == ThreadStatus.CREATED


def test_create_duplicate_raises() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    try:
        asyncio.run(store.create("t1"))
        raise AssertionError("Expected KeyError not raised")
    except KeyError:
        pass


def test_get_thread() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    record = asyncio.run(store.get("t1"))
    assert record is not None
    assert record.thread_id == "t1"


def test_get_nonexistent_returns_none() -> None:
    store = InMemoryThreadStore()
    record = asyncio.run(store.get("unknown"))
    assert record is None


# ---------------------------------------------------------------------------
# InMemoryThreadStore — transitions
# ---------------------------------------------------------------------------


def test_transition_created_to_active() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    record = asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    assert record.status == ThreadStatus.ACTIVE


def test_transition_active_to_idle() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    record = asyncio.run(store.transition("t1", ThreadStatus.IDLE))
    assert record.status == ThreadStatus.IDLE


def test_transition_active_to_interrupted() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    record = asyncio.run(store.transition("t1", ThreadStatus.INTERRUPTED))
    assert record.status == ThreadStatus.INTERRUPTED


def test_transition_interrupted_to_active() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    asyncio.run(store.transition("t1", ThreadStatus.INTERRUPTED))
    record = asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    assert record.status == ThreadStatus.ACTIVE


def test_transition_idle_to_archived() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    asyncio.run(store.transition("t1", ThreadStatus.IDLE))
    record = asyncio.run(store.transition("t1", ThreadStatus.ARCHIVED))
    assert record.status == ThreadStatus.ARCHIVED


def test_transition_idle_to_active() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    asyncio.run(store.transition("t1", ThreadStatus.IDLE))
    record = asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    assert record.status == ThreadStatus.ACTIVE


def test_invalid_transition_raises() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    try:
        asyncio.run(store.transition("t1", ThreadStatus.ARCHIVED))
        raise AssertionError("Expected ThreadTransitionError not raised")
    except ThreadTransitionError:
        pass


def test_invalid_transition_archived_terminal() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    asyncio.run(store.transition("t1", ThreadStatus.IDLE))
    asyncio.run(store.transition("t1", ThreadStatus.ARCHIVED))
    try:
        asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
        raise AssertionError("Expected ThreadTransitionError not raised")
    except ThreadTransitionError:
        pass


def test_transition_updates_updated_at() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    before = asyncio.run(store.get("t1"))
    assert before is not None
    before_ts = before.updated_at
    record = asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    # updated_at should be >= before_ts (may be equal if clock resolution is low)
    assert record.updated_at >= before_ts


def test_transition_nonexistent_raises() -> None:
    store = InMemoryThreadStore()
    try:
        asyncio.run(store.transition("missing", ThreadStatus.ACTIVE))
        raise AssertionError("Expected KeyError not raised")
    except KeyError:
        pass


# ---------------------------------------------------------------------------
# InMemoryThreadStore — run_ids
# ---------------------------------------------------------------------------


def test_add_run_id() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    record = asyncio.run(store.add_run_id("t1", "r1"))
    assert "r1" in record.run_ids


def test_add_run_id_multiple() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    asyncio.run(store.add_run_id("t1", "r1"))
    record = asyncio.run(store.add_run_id("t1", "r2"))
    assert record.run_ids == ["r1", "r2"]


# ---------------------------------------------------------------------------
# InMemoryThreadStore — archive
# ---------------------------------------------------------------------------


def test_archive_method() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    asyncio.run(store.transition("t1", ThreadStatus.ACTIVE))
    asyncio.run(store.transition("t1", ThreadStatus.IDLE))
    record = asyncio.run(store.archive("t1"))
    assert record.status == ThreadStatus.ARCHIVED
    # record still retrievable
    fetched = asyncio.run(store.get("t1"))
    assert fetched is not None
    assert fetched.status == ThreadStatus.ARCHIVED


# ---------------------------------------------------------------------------
# Defensive copy — mutations don't affect store
# ---------------------------------------------------------------------------


def test_records_are_deep_copies() -> None:
    store = InMemoryThreadStore()
    asyncio.run(store.create("t1"))
    record = asyncio.run(store.get("t1"))
    assert record is not None
    # Mutate the returned record
    record.run_ids.append("should-not-persist")
    record.metadata["key"] = "should-not-persist"
    # Fetch again — store should be unchanged
    fresh = asyncio.run(store.get("t1"))
    assert fresh is not None
    assert "should-not-persist" not in fresh.run_ids
    assert "key" not in fresh.metadata
