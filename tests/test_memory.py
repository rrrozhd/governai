"""Tests for governai.memory module — models, protocol, DictMemoryConnector, EventType."""

from __future__ import annotations

import asyncio
import time

import pytest

from governai.models.common import EventType
from governai.memory.models import MemoryEntry, MemoryScope
from governai.memory.connector import MemoryConnector
from governai.memory.dict_connector import DictMemoryConnector


# ---------- MemoryScope ----------


def test_memory_scope_values():
    assert MemoryScope.RUN.value == "run"
    assert MemoryScope.THREAD.value == "thread"
    assert MemoryScope.SHARED.value == "shared"
    assert len(MemoryScope) == 3


# ---------- MemoryEntry ----------


def test_memory_entry_roundtrip():
    entry = MemoryEntry(
        key="k", value={"x": 1}, scope=MemoryScope.RUN, scope_target="r1"
    )
    json_str = entry.model_dump_json()
    restored = MemoryEntry.model_validate_json(json_str)
    assert restored.key == "k"
    assert restored.value == {"x": 1}
    assert restored.scope == MemoryScope.RUN
    assert restored.scope_target == "r1"


def test_memory_entry_defaults():
    before = time.time()
    entry = MemoryEntry(
        key="k", value="v", scope=MemoryScope.RUN, scope_target="r1"
    )
    after = time.time()
    assert entry.created_at is not None
    assert entry.updated_at is not None
    ts = entry.created_at.timestamp()
    assert before <= ts <= after + 1
    assert entry.metadata == {}


# ---------- MemoryConnector Protocol ----------


def test_memory_connector_protocol():
    """A class with matching async def read/write/delete/search satisfies isinstance check."""

    class MyConnector:
        async def read(self, key, scope, *, target=None):
            ...

        async def write(self, key, value, scope, *, target=None):
            ...

        async def delete(self, key, scope, *, target=None):
            ...

        async def search(self, query, scope, *, target=None):
            ...

    assert isinstance(MyConnector(), MemoryConnector)


def test_external_backend_structural_subtyping():
    """A class NOT inheriting from anything, with correct signatures, passes protocol check."""

    class ExternalBackend:
        async def read(self, key, scope, *, target=None):
            return None

        async def write(self, key, value, scope, *, target=None):
            pass

        async def delete(self, key, scope, *, target=None):
            pass

        async def search(self, query, scope, *, target=None):
            return []

    obj = ExternalBackend()
    assert isinstance(obj, MemoryConnector)


# ---------- DictMemoryConnector ----------


def test_dict_connector_read_missing():
    conn = DictMemoryConnector()
    result = asyncio.run(conn.read("x", MemoryScope.RUN, target="r1"))
    assert result is None


def test_dict_connector_write_upsert():
    conn = DictMemoryConnector()

    async def _run():
        await conn.write("k", {"a": 1}, MemoryScope.RUN, target="r1")
        first = await conn.read("k", MemoryScope.RUN, target="r1")
        assert first is not None
        assert first.value == {"a": 1}
        created_at = first.created_at

        # Small delay to ensure updated_at differs
        await asyncio.sleep(0.01)

        await conn.write("k", {"a": 2}, MemoryScope.RUN, target="r1")
        second = await conn.read("k", MemoryScope.RUN, target="r1")
        assert second is not None
        assert second.value == {"a": 2}
        assert second.created_at == created_at
        assert second.updated_at > first.updated_at

    asyncio.run(_run())


def test_dict_connector_delete_missing():
    conn = DictMemoryConnector()
    with pytest.raises(KeyError):
        asyncio.run(conn.delete("x", MemoryScope.RUN, target="r1"))


def test_dict_connector_delete_existing():
    conn = DictMemoryConnector()

    async def _run():
        await conn.write("k", "v", MemoryScope.RUN, target="r1")
        await conn.delete("k", MemoryScope.RUN, target="r1")
        result = await conn.read("k", MemoryScope.RUN, target="r1")
        assert result is None

    asyncio.run(_run())


def test_dict_connector_search():
    conn = DictMemoryConnector()

    async def _run():
        await conn.write("user_name", "Alice", MemoryScope.RUN, target="r1")
        await conn.write("user_age", 30, MemoryScope.RUN, target="r1")
        await conn.write("settings", {"theme": "dark"}, MemoryScope.RUN, target="r1")

        results = await conn.search({"text": "user"}, MemoryScope.RUN, target="r1")
        keys = {e.key for e in results}
        assert keys == {"user_name", "user_age"}

    asyncio.run(_run())


def test_dict_connector_search_empty_query():
    conn = DictMemoryConnector()

    async def _run():
        await conn.write("a", 1, MemoryScope.RUN, target="r1")
        await conn.write("b", 2, MemoryScope.RUN, target="r1")

        results = await conn.search({}, MemoryScope.RUN, target="r1")
        assert len(results) == 2

    asyncio.run(_run())


def test_scope_isolation():
    conn = DictMemoryConnector()

    async def _run():
        await conn.write("k", "run_value", MemoryScope.RUN, target="r1")
        result = await conn.read("k", MemoryScope.THREAD, target="r1")
        assert result is None

    asyncio.run(_run())


# ---------- EventType ----------


def test_event_type_memory_values():
    assert EventType.MEMORY_READ == "memory_read"
    assert EventType.MEMORY_WRITE == "memory_write"
    assert EventType.MEMORY_DELETE == "memory_delete"
    assert EventType.MEMORY_SEARCH == "memory_search"


# ---------- AuditingMemoryConnector ----------


def test_auditing_connector_read_emits_event():
    from governai.memory.auditing import AuditingMemoryConnector
    from governai.audit.memory import InMemoryAuditEmitter

    async def _run():
        emitter = InMemoryAuditEmitter()
        inner = DictMemoryConnector()
        conn = AuditingMemoryConnector(
            inner, emitter, run_id="r1", thread_id="t1", workflow_name="wf1"
        )
        # Read missing key
        result = await conn.read("k", MemoryScope.RUN, target="r1")
        assert result is None
        assert len(emitter.events) == 1
        ev = emitter.events[0]
        assert ev.event_type == EventType.MEMORY_READ
        assert ev.payload["key"] == "k"
        assert ev.payload["scope"] == "run"
        assert ev.payload["found"] is False

        # Write then read existing
        await inner.write("k", "v", MemoryScope.RUN, target="r1")
        result = await conn.read("k", MemoryScope.RUN, target="r1")
        assert result is not None
        ev2 = emitter.events[-1]
        assert ev2.event_type == EventType.MEMORY_READ
        assert ev2.payload["found"] is True

    asyncio.run(_run())


def test_auditing_connector_write_emits_event():
    from governai.memory.auditing import AuditingMemoryConnector
    from governai.audit.memory import InMemoryAuditEmitter

    async def _run():
        emitter = InMemoryAuditEmitter()
        inner = DictMemoryConnector()
        conn = AuditingMemoryConnector(
            inner, emitter, run_id="r1", thread_id="t1", workflow_name="wf1"
        )
        await conn.write("k", {"secret": "data"}, MemoryScope.RUN, target="r1")
        assert len(emitter.events) == 1
        ev = emitter.events[0]
        assert ev.event_type == EventType.MEMORY_WRITE
        assert ev.payload["key"] == "k"
        assert ev.payload["scope"] == "run"

    asyncio.run(_run())


def test_auditing_write_created_flag():
    from governai.memory.auditing import AuditingMemoryConnector
    from governai.audit.memory import InMemoryAuditEmitter

    async def _run():
        emitter = InMemoryAuditEmitter()
        inner = DictMemoryConnector()
        conn = AuditingMemoryConnector(
            inner, emitter, run_id="r1", thread_id="t1", workflow_name="wf1"
        )
        # First write — created
        await conn.write("k", "v1", MemoryScope.RUN, target="r1")
        assert emitter.events[-1].payload["created"] is True

        # Second write — update
        await conn.write("k", "v2", MemoryScope.RUN, target="r1")
        assert emitter.events[-1].payload["created"] is False

    asyncio.run(_run())


def test_auditing_connector_delete_emits_on_missing():
    from governai.memory.auditing import AuditingMemoryConnector
    from governai.audit.memory import InMemoryAuditEmitter

    async def _run():
        emitter = InMemoryAuditEmitter()
        inner = DictMemoryConnector()
        conn = AuditingMemoryConnector(
            inner, emitter, run_id="r1", thread_id="t1", workflow_name="wf1"
        )
        with pytest.raises(KeyError):
            await conn.delete("x", MemoryScope.RUN, target="r1")
        # Event still emitted even on error
        assert len(emitter.events) == 1
        ev = emitter.events[0]
        assert ev.event_type == EventType.MEMORY_DELETE
        assert ev.payload["found"] is False

    asyncio.run(_run())


def test_auditing_connector_delete_emits_on_existing():
    from governai.memory.auditing import AuditingMemoryConnector
    from governai.audit.memory import InMemoryAuditEmitter

    async def _run():
        emitter = InMemoryAuditEmitter()
        inner = DictMemoryConnector()
        conn = AuditingMemoryConnector(
            inner, emitter, run_id="r1", thread_id="t1", workflow_name="wf1"
        )
        await inner.write("k", "v", MemoryScope.RUN, target="r1")
        await conn.delete("k", MemoryScope.RUN, target="r1")
        ev = emitter.events[-1]
        assert ev.event_type == EventType.MEMORY_DELETE
        assert ev.payload["found"] is True

    asyncio.run(_run())


def test_auditing_connector_search_emits_event():
    from governai.memory.auditing import AuditingMemoryConnector
    from governai.audit.memory import InMemoryAuditEmitter

    async def _run():
        emitter = InMemoryAuditEmitter()
        inner = DictMemoryConnector()
        conn = AuditingMemoryConnector(
            inner, emitter, run_id="r1", thread_id="t1", workflow_name="wf1"
        )
        await inner.write("k1", "v1", MemoryScope.RUN, target="r1")
        await inner.write("k2", "v2", MemoryScope.RUN, target="r1")
        results = await conn.search({"text": "k"}, MemoryScope.RUN, target="r1")
        assert len(results) == 2
        ev = emitter.events[-1]
        assert ev.event_type == EventType.MEMORY_SEARCH
        assert ev.payload["query"] == {"text": "k"}
        assert ev.payload["scope"] == "run"
        assert ev.payload["result_count"] == 2

    asyncio.run(_run())


def test_auditing_write_no_value_in_payload():
    from governai.memory.auditing import AuditingMemoryConnector
    from governai.audit.memory import InMemoryAuditEmitter

    async def _run():
        emitter = InMemoryAuditEmitter()
        inner = DictMemoryConnector()
        conn = AuditingMemoryConnector(
            inner, emitter, run_id="r1", thread_id="t1", workflow_name="wf1"
        )
        await conn.write("k", {"secret": "data"}, MemoryScope.RUN, target="r1")
        ev = emitter.events[-1]
        assert "value" not in ev.payload

    asyncio.run(_run())


def test_auditing_search_no_values_in_payload():
    from governai.memory.auditing import AuditingMemoryConnector
    from governai.audit.memory import InMemoryAuditEmitter

    async def _run():
        emitter = InMemoryAuditEmitter()
        inner = DictMemoryConnector()
        conn = AuditingMemoryConnector(
            inner, emitter, run_id="r1", thread_id="t1", workflow_name="wf1"
        )
        await inner.write("k", "v", MemoryScope.RUN, target="r1")
        await conn.search({}, MemoryScope.RUN, target="r1")
        ev = emitter.events[-1]
        assert "results" not in ev.payload
        assert "values" not in ev.payload

    asyncio.run(_run())


# ---------- ScopedMemoryConnector ----------


def test_scoped_memory_run_scope():
    """ScopedMemoryConnector write with RUN scope uses run_id as target."""
    from governai.memory.scoped import ScopedMemoryConnector

    async def _run():
        inner = DictMemoryConnector()
        scoped = ScopedMemoryConnector(
            inner, run_id="r1", thread_id="t1", workflow_name="wf"
        )
        await scoped.write("k", "v", MemoryScope.RUN)
        # Data should land at target="r1"
        entry = await inner.read("k", MemoryScope.RUN, target="r1")
        assert entry is not None
        assert entry.value == "v"

    asyncio.run(_run())


def test_scoped_memory_thread_scope():
    """ScopedMemoryConnector write with THREAD scope uses thread_id as target."""
    from governai.memory.scoped import ScopedMemoryConnector

    async def _run():
        inner = DictMemoryConnector()
        scoped = ScopedMemoryConnector(
            inner, run_id="r1", thread_id="t1", workflow_name="wf"
        )
        await scoped.write("k", "v", MemoryScope.THREAD)
        entry = await inner.read("k", MemoryScope.THREAD, target="t1")
        assert entry is not None
        assert entry.value == "v"

    asyncio.run(_run())


def test_scoped_memory_shared_scope():
    """ScopedMemoryConnector write with SHARED scope uses '__shared__' as target."""
    from governai.memory.scoped import ScopedMemoryConnector

    async def _run():
        inner = DictMemoryConnector()
        scoped = ScopedMemoryConnector(
            inner, run_id="r1", thread_id="t1", workflow_name="wf"
        )
        await scoped.write("k", "v", MemoryScope.SHARED)
        entry = await inner.read("k", MemoryScope.SHARED, target="__shared__")
        assert entry is not None
        assert entry.value == "v"

    asyncio.run(_run())


def test_scoped_memory_thread_fallback():
    """ScopedMemoryConnector with thread_id=None uses run_id as fallback for THREAD scope."""
    from governai.memory.scoped import ScopedMemoryConnector

    async def _run():
        inner = DictMemoryConnector()
        scoped = ScopedMemoryConnector(
            inner, run_id="r1", thread_id=None, workflow_name="wf"
        )
        await scoped.write("k", "v", MemoryScope.THREAD)
        # Falls back to run_id
        entry = await inner.read("k", MemoryScope.THREAD, target="r1")
        assert entry is not None
        assert entry.value == "v"

    asyncio.run(_run())


def test_scoped_memory_explicit_target_override():
    """Explicit target overrides automatic scope resolution (D-03)."""
    from governai.memory.scoped import ScopedMemoryConnector

    async def _run():
        inner = DictMemoryConnector()
        scoped = ScopedMemoryConnector(
            inner, run_id="r1", thread_id="t1", workflow_name="wf"
        )
        await scoped.write("k", "v", MemoryScope.RUN, target="custom")
        # Data should land at target="custom", not "r1"
        entry = await inner.read("k", MemoryScope.RUN, target="custom")
        assert entry is not None
        assert entry.value == "v"
        # Should NOT be at run_id target
        entry_at_run = await inner.read("k", MemoryScope.RUN, target="r1")
        assert entry_at_run is None

    asyncio.run(_run())


# ---------- ExecutionContext memory ----------


def test_execution_context_memory_accessor():
    """ExecutionContext with memory_connector returns ScopedMemoryConnector from ctx.memory."""
    from governai.memory.scoped import ScopedMemoryConnector
    from governai.runtime.context import ExecutionContext

    inner = DictMemoryConnector()
    ctx = ExecutionContext(
        run_id="r1",
        workflow_name="wf",
        step_name="step1",
        artifacts={},
        memory_connector=inner,
    )
    assert ctx.memory is not None
    assert isinstance(ctx.memory, ScopedMemoryConnector)


def test_execution_context_memory_none():
    """ExecutionContext without memory_connector returns None from ctx.memory."""
    from governai.runtime.context import ExecutionContext

    ctx = ExecutionContext(
        run_id="r1",
        workflow_name="wf",
        step_name="step1",
        artifacts={},
    )
    assert ctx.memory is None


def test_execution_context_memory_with_audit():
    """ExecutionContext with both memory_connector and audit_emitter wraps with AuditingMemoryConnector."""
    from governai.memory.scoped import ScopedMemoryConnector
    from governai.audit.memory import InMemoryAuditEmitter
    from governai.runtime.context import ExecutionContext

    inner = DictMemoryConnector()
    emitter = InMemoryAuditEmitter()
    ctx = ExecutionContext(
        run_id="r1",
        workflow_name="wf",
        step_name="step1",
        artifacts={},
        memory_connector=inner,
        audit_emitter=emitter,
    )
    assert ctx.memory is not None
    assert isinstance(ctx.memory, ScopedMemoryConnector)
    # The inner of the ScopedMemoryConnector should be an AuditingMemoryConnector
    from governai.memory.auditing import AuditingMemoryConnector
    assert isinstance(ctx.memory._connector, AuditingMemoryConnector)
