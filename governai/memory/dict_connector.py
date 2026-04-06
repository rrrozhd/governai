"""DictMemoryConnector: in-memory default backend for MemoryConnector."""

from __future__ import annotations

from datetime import datetime, timezone

from governai.memory.models import MemoryEntry, MemoryScope
from governai.models.common import JSONValue


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DictMemoryConnector:
    """In-memory MemoryConnector implementation using nested dicts.

    Storage layout: _store[scope.value][target][key] = MemoryEntry
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, dict[str, MemoryEntry]]] = {}

    async def read(
        self, key: str, scope: MemoryScope, *, target: str | None = None
    ) -> MemoryEntry | None:
        entry = self._store.get(scope.value, {}).get(target or "", {}).get(key)
        if entry is None:
            return None
        return entry.model_copy(deep=True)

    async def write(
        self, key: str, value: JSONValue, scope: MemoryScope, *, target: str | None = None
    ) -> None:
        scope_key = scope.value
        target_key = target or ""
        bucket = self._store.setdefault(scope_key, {}).setdefault(target_key, {})
        existing = bucket.get(key)
        if existing is not None:
            bucket[key] = existing.model_copy(
                update={"value": value, "updated_at": _utcnow()}, deep=True
            )
        else:
            bucket[key] = MemoryEntry(
                key=key, value=value, scope=scope, scope_target=target_key
            )

    async def delete(
        self, key: str, scope: MemoryScope, *, target: str | None = None
    ) -> None:
        bucket = self._store.get(scope.value, {}).get(target or "", {})
        if key not in bucket:
            raise KeyError(key)
        del bucket[key]

    async def search(
        self, query: dict, scope: MemoryScope, *, target: str | None = None
    ) -> list[MemoryEntry]:
        bucket = self._store.get(scope.value, {}).get(target or "", {})
        text = query.get("text", "").lower()
        results = []
        for entry in bucket.values():
            if not text or text in entry.key.lower() or text in str(entry.value).lower():
                results.append(entry.model_copy(deep=True))
        return results
