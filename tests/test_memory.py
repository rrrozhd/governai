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
