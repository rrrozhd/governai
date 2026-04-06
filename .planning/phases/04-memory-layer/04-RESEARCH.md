# Phase 4: Memory Layer - Research

**Researched:** 2026-04-06
**Domain:** Python typing.Protocol, async key-value memory connectors, audit decorator pattern, Pydantic data models
**Confidence:** HIGH

## Summary

Phase 4 adds a governed memory system to GovernAI. The design is fully specified in CONTEXT.md with no ambiguous decisions remaining except minor implementation details (enum placement, default connector choice, ScopedMemoryConnector internals). All major choices — Protocol shape, scope names, audit decorator pattern, RunState isolation, and runtime wiring — are locked.

The implementation follows a single, well-established blueprint already present in the codebase. `MemoryConnector` mirrors `SecretsProvider` (typing.Protocol, async-first, structurally typed). `AuditingMemoryConnector` mirrors `RedactingAuditEmitter` (wrapping decorator, transparent to backend). `DictMemoryConnector` mirrors `InMemoryThreadStore` (nested dict, `model_copy(deep=True)` defensive copies). All wiring in `LocalRuntime` and `ExecutionContext` mirrors the secrets integration added in Phase 3.

The only meaningful design work this phase is (a) adding four `EventType` values, (b) defining `MemoryScope`, `MemoryEntry`, and the `MemoryConnector` protocol, (c) building `DictMemoryConnector` and `AuditingMemoryConnector`, (d) plumbing `ctx.memory` through `ExecutionContext`, and (e) auto-wrapping in `LocalRuntime.__init__()`. No new external dependencies are required.

**Primary recommendation:** Follow the secrets + thread_store precedent exactly. The codebase already contains three complete reference implementations — use them as templates, not inspiration.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Scope Model**
- D-01: Explicit scope argument — tools pass a MemoryScope enum (run/thread/shared) to each read/write/delete/search call. Mirrors Zeroth's ConnectorScope naming for migration alignment.
- D-02: Scope names align with Zeroth: `run`, `thread`, `shared` (not workflow/global as in MEM-01 requirement text). `run` = per-run ephemeral, `thread` = per-conversation, `shared` = global across all runs/threads.
- D-03: Auto-fill scope targets from ExecutionContext — thread scope defaults to current thread_id, run scope to current run_id. Explicit target override still available for cross-scope access.
- D-04: Cross-scope reads are unrestricted — any scope can read any scope. Writes respect declared scope only.

**Connector Protocol Shape**
- D-05: MemoryConnector is a `typing.Protocol` (structural subtyping, like SecretsProvider). Not an ABC. Follows PROJECT.md "Protocols over implementations" principle. External backends satisfy the protocol without inheriting.
- D-06: Protocol surface: `read(key, scope) -> MemoryEntry | None`, `write(key, value, scope)`, `delete(key, scope)`, `search(query, scope) -> list[MemoryEntry]`. Search is included from day one for RAG/vector DB use cases.
- D-07: Async-first — all methods are `async def`. Consistent with GovernAI convention (RunStore, InterruptStore, ThreadStore).
- D-08: Key-value data model with JSON payload — `value` is `JSONValue` (dict/list/str/etc). Matches Pydantic patterns.
- D-09: `search()` takes a generic `query: dict` parameter — backend interprets query shape. Vector stores use `{'text': ..., 'top_k': ...}`, Postgres uses `{'filter': ...}`. Protocol stays backend-agnostic.
- D-10: Single connector per runtime — LocalRuntime receives one MemoryConnector. No named registry at the GovernAI layer.

**MemoryEntry Model**
- D-11: MemoryEntry carries: `key: str`, `value: JSONValue`, `scope: MemoryScope`, `scope_target: str`, `created_at: datetime`, `updated_at: datetime`, `metadata: dict[str, Any]`. Timestamps for future TTL/LRU. Metadata dict for tags, labels, vector store similarity scores.
- D-12: `search()` returns full `list[MemoryEntry]` objects — avoids N+1 read-after-search pattern.

**Audit Integration**
- D-13: AuditingMemoryConnector wrapping pattern — decorates any MemoryConnector and emits audit events. Mirrors RedactingAuditEmitter decorator pattern.
- D-14: Four dedicated audit event types: `MEMORY_READ`, `MEMORY_WRITE`, `MEMORY_DELETE`, `MEMORY_SEARCH`. Each is a distinct EventType enum value.
- D-15: Audit payload carries key + scope + metadata, no value — memory values could be large or sensitive.
- D-16: MEMORY_WRITE payload includes `{created: true/false}` to distinguish create vs update. MEMORY_DELETE payload includes `{found: true/false}`.
- D-17: MEMORY_SEARCH payload carries query (without values) + result_count.
- D-18: AuditingMemoryConnector uses `emit_event()` helper — consistent with all other audit emission points.
- D-19: Memory and secrets are separate concerns — AuditingMemoryConnector does NOT register memory values with SecretRegistry.

**Runtime Wiring**
- D-20: Tools access memory via `ctx.memory` on ExecutionContext — a ScopedMemoryConnector wrapper that knows current thread_id, run_id, workflow_name.
- D-21: AuditingMemoryConnector wrapping happens automatically in LocalRuntime.__init__() when both memory_connector and audit_emitter are present.
- D-22: `memory_connector` is an optional parameter on LocalRuntime, like all other injectables.

**Error Handling**
- D-23: `read()` on non-existent key returns `None` — expected behavior, not an error state.
- D-24: `delete()` on non-existent key raises `KeyError` — governance-first approach.
- D-25: `write()` is upsert — creates or updates silently.
- D-26: All operations emit audit events regardless of outcome.

**DictMemoryConnector**
- D-27: Nested dict storage: `dict[scope][target][key] -> MemoryEntry`. Natural scope isolation.
- D-28: `search()` implementation: key substring match + value text match within scope.

### Claude's Discretion
- Default memory_connector when none provided to LocalRuntime (DictMemoryConnector vs NullMemoryConnector)
- ScopedMemoryConnector internal design (thin wrapper or full proxy)
- MemoryScope enum placement (models/common.py vs dedicated memory module)
- MemoryEntry Pydantic model field ordering and validation rules
- DictMemoryConnector thread-safety approach (single-threaded asyncio assumption vs locks)
- Exact `connector_type` attribute handling (whether GovernAI protocol includes it like Zeroth or omits it)

### Deferred Ideas (OUT OF SCOPE)
- MEM-04: Redis-backed MemoryConnector (v2 requirement)
- MEM-05: Vector store MemoryConnector for semantic search (v2 requirement)
- MEM-06: Memory retention policies / TTL-based expiry per scope (v2 requirement)
- Named connector registry at GovernAI layer (Zeroth handles this today)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEM-01 | MemoryConnector protocol defines read/write/search with scope binding (thread, workflow, global) | D-05 through D-09 define the full Protocol surface; scope names are `run`/`thread`/`shared` per D-02 (requirement text uses "workflow/global" but D-02 locks the canonical names). SecretsProvider is the direct template. |
| MEM-02 | Memory writes emit audit events (MEMORY_WRITE, MEMORY_READ event types) | D-13 through D-18 fully specify AuditingMemoryConnector. Four EventType values needed in models/common.py. RedactingAuditEmitter is the direct template. |
| MEM-03 | In-memory MemoryConnector implementation ships as default; backends are pluggable | D-27/D-28 specify DictMemoryConnector. MEM-03 success criterion 3 requires RunState isolation — D-20 (ScopedMemoryConnector) satisfies this by keeping only references in ExecutionContext, not values in RunState. |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `typing` stdlib | 3.12+ | `typing.Protocol`, `runtime_checkable` | Already used for SecretsProvider — same pattern |
| Pydantic | >=2.7,<3 | MemoryEntry model, JSON validation | Project standard; all data models use BaseModel |
| Python `enum` stdlib | 3.12+ | MemoryScope (str enum, like ConnectorScope in Zeroth) | Project standard for all enum types |
| Python `datetime` stdlib | 3.12+ | MemoryEntry timestamps (created_at, updated_at) | Same pattern as ThreadRecord |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio` stdlib | 3.12+ | Single-threaded concurrency assumption for DictMemoryConnector | No locks needed for dict in async context |

No new pip dependencies required. This phase is pure Python stdlib + project-already-present Pydantic.

**Installation:**
```bash
# No new dependencies
```

**Version verification:** All dependencies are stdlib or already in pyproject.toml. Pydantic >=2.7,<3 is locked. Python >=3.12 is required.

---

## Architecture Patterns

### Recommended Project Structure

```
governai/
├── memory/
│   ├── __init__.py          # exports MemoryConnector, MemoryEntry, MemoryScope, DictMemoryConnector, AuditingMemoryConnector
│   ├── connector.py         # MemoryConnector Protocol + NullMemoryConnector (or DictMemoryConnector as default)
│   ├── models.py            # MemoryEntry, MemoryScope
│   ├── dict_connector.py    # DictMemoryConnector implementation
│   └── auditing.py          # AuditingMemoryConnector (wrapping decorator)
├── models/
│   └── common.py            # EventType enum — add MEMORY_READ, MEMORY_WRITE, MEMORY_DELETE, MEMORY_SEARCH
├── runtime/
│   ├── context.py           # ExecutionContext — add ctx.memory (ScopedMemoryConnector)
│   └── local.py             # LocalRuntime — add memory_connector param + auto-wrap
└── __init__.py              # export new public types
tests/
└── test_memory.py           # comprehensive tests for all new components
```

**Rationale:** A dedicated `governai/memory/` module follows the `governai/runtime/` pattern for component grouping. Keeping `MemoryScope` and `MemoryEntry` in `governai/memory/models.py` is cleaner than adding them to `models/common.py`, which already carries EventType, RunStatus, and DeterminismMode. The `__init__.py` re-exports everything needed publicly.

### Pattern 1: typing.Protocol for Connector Interface (mirrors SecretsProvider)

**What:** Structural subtyping — any class with the right method signatures satisfies the protocol without inheritance. Decorated with `@runtime_checkable` to allow `isinstance()` checks in tests.

**When to use:** Consumer-facing injectable dependencies where external backends must not inherit from GovernAI base classes.

**Example:**
```python
# Source: governai/runtime/secrets.py (direct template)
from __future__ import annotations
from typing import Protocol, runtime_checkable
from governai.memory.models import MemoryEntry, MemoryScope
from governai.models.common import JSONValue


@runtime_checkable
class MemoryConnector(Protocol):
    async def read(self, key: str, scope: MemoryScope, *, target: str | None = None) -> MemoryEntry | None: ...
    async def write(self, key: str, value: JSONValue, scope: MemoryScope, *, target: str | None = None) -> None: ...
    async def delete(self, key: str, scope: MemoryScope, *, target: str | None = None) -> None: ...
    async def search(self, query: dict, scope: MemoryScope, *, target: str | None = None) -> list[MemoryEntry]: ...
```

### Pattern 2: Decorator/Wrapping for Cross-Cutting Concerns (mirrors RedactingAuditEmitter)

**What:** A wrapper class holds a reference to the inner connector and intercepts every method call to emit audit events before delegating.

**When to use:** Audit, metrics, logging — anything that shouldn't pollute backend implementations.

**Example:**
```python
# Source: governai/runtime/secrets.py RedactingAuditEmitter (direct template)
class AuditingMemoryConnector:
    def __init__(self, inner: MemoryConnector, emitter: AuditEmitter,
                 run_id: str, thread_id: str | None, workflow_name: str) -> None:
        self._inner = inner
        self._emitter = emitter
        self._run_id = run_id
        self._thread_id = thread_id
        self._workflow_name = workflow_name

    async def read(self, key: str, scope: MemoryScope, *, target: str | None = None) -> MemoryEntry | None:
        result = await self._inner.read(key, scope, target=target)
        await emit_event(
            self._emitter,
            run_id=self._run_id,
            thread_id=self._thread_id,
            workflow_name=self._workflow_name,
            event_type=EventType.MEMORY_READ,
            payload={"key": key, "scope": scope.value, "found": result is not None},
        )
        return result
```

**Note:** AuditingMemoryConnector needs `run_id`, `thread_id`, and `workflow_name` to call `emit_event()`. These are available at the time the wrapper is constructed inside the execution call (not at `LocalRuntime.__init__()` time). See Pitfall 2 below for resolution.

### Pattern 3: ScopedMemoryConnector — thin wrapper on ExecutionContext

**What:** `ctx.memory` is not the raw connector — it is a `ScopedMemoryConnector` that pre-fills `target` from `ctx.run_id`, `ctx.workflow_name`, etc., so tools can call `ctx.memory.write("key", value, MemoryScope.THREAD)` without specifying `thread_id`.

**When to use:** Every ExecutionContext creation where a memory_connector is present.

**Example:**
```python
# Pattern based on ExecutionContext.resolve_secret()
class ScopedMemoryConnector:
    """Thin wrapper that pre-fills scope targets from ExecutionContext."""

    def __init__(self, connector: MemoryConnector, *, run_id: str, thread_id: str | None, workflow_name: str) -> None:
        self._connector = connector
        self._run_id = run_id
        self._thread_id = thread_id
        self._workflow_name = workflow_name

    async def read(self, key: str, scope: MemoryScope, *, target: str | None = None) -> MemoryEntry | None:
        resolved_target = target or self._resolve_target(scope)
        return await self._connector.read(key, scope, target=resolved_target)

    def _resolve_target(self, scope: MemoryScope) -> str:
        if scope == MemoryScope.RUN:
            return self._run_id
        if scope == MemoryScope.THREAD:
            return self._thread_id or self._run_id
        return "__shared__"  # shared scope: single global namespace
```

### Pattern 4: DictMemoryConnector nested dict storage (mirrors InMemoryThreadStore)

**What:** Nested dict `dict[scope_value][target][key] -> MemoryEntry`. Scope isolation is structural, not enforced by any lock.

**When to use:** Default in-memory backend; good for testing any code that uses MemoryConnector.

**Example:**
```python
# Source: governai/runtime/thread_store.py InMemoryThreadStore (structural template)
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from governai.memory.models import MemoryEntry, MemoryScope
from governai.models.common import JSONValue


class DictMemoryConnector:
    def __init__(self) -> None:
        # _store[scope_value][target][key] -> MemoryEntry
        self._store: dict[str, dict[str, dict[str, MemoryEntry]]] = {}

    async def read(self, key: str, scope: MemoryScope, *, target: str | None = None) -> MemoryEntry | None:
        return self._store.get(scope.value, {}).get(target or "", {}).get(key)

    async def write(self, key: str, value: JSONValue, scope: MemoryScope, *, target: str | None = None) -> None:
        bucket = self._store.setdefault(scope.value, {}).setdefault(target or "", {})
        now = datetime.now(timezone.utc)
        if key in bucket:
            entry = bucket[key]
            bucket[key] = entry.model_copy(update={"value": value, "updated_at": now}, deep=True)
        else:
            bucket[key] = MemoryEntry(key=key, value=value, scope=scope, scope_target=target or "", created_at=now, updated_at=now)

    async def delete(self, key: str, scope: MemoryScope, *, target: str | None = None) -> None:
        bucket = self._store.get(scope.value, {}).get(target or "", {})
        if key not in bucket:
            raise KeyError(f"Memory key not found: {key!r} in scope={scope.value}, target={target!r}")
        del bucket[key]

    async def search(self, query: dict, scope: MemoryScope, *, target: str | None = None) -> list[MemoryEntry]:
        bucket = self._store.get(scope.value, {}).get(target or "", {})
        q = str(query.get("text", "")).lower()
        if not q:
            return list(bucket.values())
        results = []
        for entry in bucket.values():
            if q in entry.key.lower() or q in str(entry.value).lower():
                results.append(entry)
        return results
```

### Pattern 5: LocalRuntime auto-wrapping (mirrors secrets wiring)

**What:** `LocalRuntime.__init__()` stores the raw `memory_connector`. The audit wrapping is NOT done at init time (see Pitfall 2) — it's applied per-execution when `run_id` and `thread_id` are known.

**When to use:** Each call to `_execute_tool()` (or equivalent) passes a freshly-constructed AuditingMemoryConnector into ScopedMemoryConnector.

### Anti-Patterns to Avoid

- **Storing memory values in RunState:** RunState is serialized and checkpointed. Memory values can be unbounded in size. The point of MemoryConnector is to externalize memory storage. `ctx.memory` holds a reference to the connector, not the data.
- **Wrapping AuditingMemoryConnector at LocalRuntime.__init__ time:** `emit_event()` requires `run_id` and `workflow_name`, which are not known until a run starts. The wrapper must be constructed per-execution, not per-runtime.
- **Inheriting from an ABC for MemoryConnector:** The protocol is structural. External backends (Redis, Chroma, Postgres) must not need to import GovernAI base classes.
- **Locking DictMemoryConnector dicts:** asyncio is single-threaded. Python dict operations are GIL-atomic. Adding locks adds complexity with zero benefit for the target use case.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Audit emission | Custom logging in each connector method | `emit_event()` helper from `governai/audit/emitter.py` | Already handles AuditEvent construction, UUID generation, timestamp — identical to every other audit point in the codebase |
| JSON serialization of MemoryEntry | Custom `to_dict()` methods | `Pydantic BaseModel.model_dump_json()` / `model_validate_json()` | Already used by all models; handles datetime, nested types, aliases automatically |
| Scope target resolution | Inline string logic in each connector method | ScopedMemoryConnector wrapper on ExecutionContext | Centralizes the `run_id`/`thread_id` → scope_target mapping in one place; connectors stay target-agnostic |
| Protocol conformance checking | Manual duck-typing guards | `@runtime_checkable` + `isinstance(obj, MemoryConnector)` | Already used for SecretsProvider; gives clear test assertions |

**Key insight:** Every piece of infrastructure this phase needs already exists in the codebase. The work is wiring existing components into the new memory module, not building new infrastructure.

---

## Common Pitfalls

### Pitfall 1: AuditingMemoryConnector emitting value in payload

**What goes wrong:** Developer includes `value` in the MEMORY_WRITE audit payload, leaking potentially large or sensitive memory values into the audit stream.

**Why it happens:** It seems natural to log what was written.

**How to avoid:** Per D-15, audit payload carries `key + scope + metadata` only. For MEMORY_WRITE, payload is: `{"key": key, "scope": scope.value, "target": resolved_target, "created": <bool>}`. No `value` field.

**Warning signs:** Test that constructs an AuditingMemoryConnector write call and checks the emitted event payload must assert `"value" not in event.payload`.

### Pitfall 2: Constructing AuditingMemoryConnector at LocalRuntime.__init__ time

**What goes wrong:** `emit_event()` requires `run_id`, `thread_id`, and `workflow_name`. These are not known at `LocalRuntime.__init__()` time — they only exist once a workflow run starts.

**Why it happens:** The secrets pattern (wrapping at init time) works for `RedactingAuditEmitter` because redaction doesn't call `emit_event()` directly — it just transforms the event. AuditingMemoryConnector actively emits new events.

**How to avoid:** Two valid approaches:
1. Store the raw `memory_connector` on `LocalRuntime`, and construct `AuditingMemoryConnector` inside each execution (where `state.run_id`, `state.workflow_name`, `state.thread_id` are available), then pass it to `ScopedMemoryConnector` for the ExecutionContext.
2. Store `memory_connector` on `LocalRuntime` without wrapping. Pass both `memory_connector` and `audit_emitter` into `ScopedMemoryConnector`, which builds the `AuditingMemoryConnector` lazily at call time.

**Warning signs:** If wrapping at init, any test that calls `ctx.memory.write(...)` and then checks `emitter.events` for a MEMORY_WRITE event with the correct `run_id` will fail because `run_id` was unknown at wrap time.

### Pitfall 3: MemoryScope using str Enum causing serialization surprises

**What goes wrong:** `MemoryScope` inherits from `str, Enum` but payload serialization passes the enum object rather than `.value`. Pydantic will serialize correctly, but hand-written `payload={"scope": scope}` passes the enum, not the string.

**Why it happens:** Python `str` enum `scope.value` and `scope` look identical in many contexts but differ in JSON serialization.

**How to avoid:** Always use `scope.value` explicitly in audit payloads: `"scope": scope.value`. Check the EventType enum in `models/common.py` — it uses `str, Enum` and values are lowercase strings.

**Warning signs:** Audit event payload check that asserts `event.payload["scope"] == "thread"` fails because payload contains `MemoryScope.THREAD` object.

### Pitfall 4: Shared-scope target name collision

**What goes wrong:** DictMemoryConnector uses `target or ""` as the bucket key. For `MemoryScope.SHARED`, the target should be a fixed global key (e.g., `"__shared__"`), not an empty string that looks like a missing thread_id target.

**Why it happens:** `ScopedMemoryConnector._resolve_target()` must return a non-empty, unambiguous string for shared scope. Empty string is a valid `str` but is confusing in dict keys.

**How to avoid:** Use a sentinel like `"__shared__"` for shared scope in `ScopedMemoryConnector._resolve_target()`. Document it. DictMemoryConnector doesn't care what the target string is — it just uses it as a dict key.

### Pitfall 5: MEMORY_DELETE on non-existent key: D-26 says "emit regardless of outcome"

**What goes wrong:** Developer wraps the `delete()` call with try/except and returns early before emitting the audit event when the key is not found.

**Why it happens:** Audit emission feels like a "success path" operation.

**How to avoid:** Per D-26, the AuditingMemoryConnector must emit the MEMORY_DELETE event *before or after* raising the KeyError from the inner connector. Pattern: call inner first (capture exception), emit audit event with `{found: false}`, then re-raise. Alternatively, emit first then call inner.

```python
async def delete(self, key: str, scope: MemoryScope, *, target: str | None = None) -> None:
    found = True
    try:
        await self._inner.delete(key, scope, target=target)
    except KeyError:
        found = False
        raise
    finally:
        await emit_event(self._emitter, ..., payload={"key": key, "scope": scope.value, "found": found})
```

---

## Code Examples

### MemoryEntry model
```python
# Pattern source: governai/runtime/thread_store.py ThreadRecord
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field
from governai.memory.models import MemoryScope
from governai.models.common import JSONValue


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryEntry(BaseModel):
    key: str
    value: JSONValue
    scope: MemoryScope
    scope_target: str
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

### MemoryScope enum
```python
# Pattern source: zeroth/memory/models.py ConnectorScope — same values
from enum import StrEnum

class MemoryScope(StrEnum):
    RUN = "run"
    THREAD = "thread"
    SHARED = "shared"
```

**Note on StrEnum vs str+Enum:** Zeroth uses `StrEnum` (Python 3.11+). GovernAI already uses `class EventType(str, Enum)` and `class RunStatus(str, Enum)`. For consistency, use `class MemoryScope(str, Enum)` to match the existing codebase pattern, not `StrEnum`. Both produce equivalent string behavior.

### EventType additions
```python
# In governai/models/common.py — append to EventType enum
MEMORY_READ = "memory_read"
MEMORY_WRITE = "memory_write"
MEMORY_DELETE = "memory_delete"
MEMORY_SEARCH = "memory_search"
```

### LocalRuntime memory_connector parameter
```python
# Pattern source: LocalRuntime.__init__() secrets_provider wiring (lines 74, 102-104)
def __init__(
    self,
    *,
    # ... existing params ...
    memory_connector: MemoryConnector | None = None,
) -> None:
    # Per D-22: optional injectable
    self._memory_connector = memory_connector or DictMemoryConnector()
    # NOTE: Do NOT wrap with AuditingMemoryConnector here — run_id unknown at init time
```

### ExecutionContext ctx.memory
```python
# Pattern source: ExecutionContext.__init__() secrets_provider wiring
def __init__(
    self,
    *,
    # ... existing params ...
    memory_connector: MemoryConnector | None = None,
    audit_emitter: AuditEmitter | None = None,
    thread_id: str | None = None,
) -> None:
    # ...
    if memory_connector is not None and audit_emitter is not None:
        auditing = AuditingMemoryConnector(
            inner=memory_connector,
            emitter=audit_emitter,
            run_id=run_id,
            thread_id=thread_id,
            workflow_name=workflow_name,
        )
        self._memory: ScopedMemoryConnector | None = ScopedMemoryConnector(
            auditing, run_id=run_id, thread_id=thread_id, workflow_name=workflow_name
        )
    elif memory_connector is not None:
        self._memory = ScopedMemoryConnector(
            memory_connector, run_id=run_id, thread_id=thread_id, workflow_name=workflow_name
        )
    else:
        self._memory = None

@property
def memory(self) -> ScopedMemoryConnector | None:
    return self._memory
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Zeroth sync MemoryConnector (read/write only) | GovernAI async + delete + search | Phase 4 (now) | Zeroth wraps GovernAI connectors at its layer; GovernAI targets real async backends |
| RunState carrying all agent data | MemoryConnector externalizes memory | Phase 4 design | RunState stays bounded; connector holds arbitrarily large memory |

**Deprecated/outdated:**
- Zeroth's `connector_type: str` attribute on Protocol: The CONTEXT.md marks this as "Claude's Discretion" — GovernAI can omit it since structural subtyping only requires the method signatures. Recommend omitting to keep the protocol minimal.

---

## Open Questions

1. **Default when no memory_connector provided to LocalRuntime**
   - What we know: D-22 says optional. Secrets uses `NullSecretsProvider` (raises on use). Thread_store uses `InMemoryThreadStore` (works out of box).
   - What's unclear: MEM-03 success criterion says "works out of the box with no configuration." This implies `DictMemoryConnector` as default, not a Null variant.
   - Recommendation: Default to `DictMemoryConnector()` (not None, not NullMemoryConnector). This satisfies MEM-03's "out of the box" requirement. Tools that call `ctx.memory` when no connector is configured are an application error, not a governance error.

2. **Where to put MemoryScope and MemoryEntry**
   - What we know: CONTEXT.md marks enum placement as Claude's Discretion.
   - What's unclear: `models/common.py` is already used for `JSONValue`, `EventType`, etc. A dedicated `governai/memory/` module is cleaner.
   - Recommendation: `governai/memory/models.py` for `MemoryScope` and `MemoryEntry`. `JSONValue` is already in `models/common.py` — import from there. This matches how `ThreadRecord`/`ThreadStatus` live in `runtime/thread_store.py` rather than `models/`.

3. **ctx.memory return type when no connector is configured**
   - What we know: Tools call `ctx.memory.write(...)` — if `ctx.memory` is `None`, this raises `AttributeError` at runtime.
   - What's unclear: Should the accessor raise a descriptive error, or return None and let callers check?
   - Recommendation: Return `None` and let caller check (consistent with `ctx.approval_request` which is `Optional`). Document that tools should check `if ctx.memory is not None` or rely on the runtime always providing a connector.

---

## Environment Availability

Step 2.6: SKIPPED — Phase 4 adds no external dependencies. DictMemoryConnector uses only Python stdlib (`dict`, `datetime`). No new pip packages are required. All tooling (pytest, Pydantic, Python 3.12) is already established in the project.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >= 8.0 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` testpaths = ["tests"] |
| Quick run command | `uv run pytest tests/test_memory.py -x` |
| Full suite command | `uv run pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MEM-01 | MemoryConnector protocol — class with correct async methods satisfies it | unit | `uv run pytest tests/test_memory.py::test_memory_connector_protocol -x` | Wave 0 |
| MEM-01 | MemoryScope enum has values run/thread/shared | unit | `uv run pytest tests/test_memory.py::test_memory_scope_values -x` | Wave 0 |
| MEM-01 | MemoryEntry model roundtrip (model_dump_json / model_validate_json) | unit | `uv run pytest tests/test_memory.py::test_memory_entry_roundtrip -x` | Wave 0 |
| MEM-01 | DictMemoryConnector.read returns None for missing key | unit | `uv run pytest tests/test_memory.py::test_dict_connector_read_missing -x` | Wave 0 |
| MEM-01 | DictMemoryConnector.write is upsert (create then update) | unit | `uv run pytest tests/test_memory.py::test_dict_connector_write_upsert -x` | Wave 0 |
| MEM-01 | DictMemoryConnector.delete raises KeyError on missing key | unit | `uv run pytest tests/test_memory.py::test_dict_connector_delete_missing -x` | Wave 0 |
| MEM-01 | DictMemoryConnector.search — text match within scope | unit | `uv run pytest tests/test_memory.py::test_dict_connector_search -x` | Wave 0 |
| MEM-01 | Scope isolation: run-scope data not visible to thread-scope | unit | `uv run pytest tests/test_memory.py::test_scope_isolation -x` | Wave 0 |
| MEM-02 | MEMORY_WRITE event emitted on write, payload has no value field | unit | `uv run pytest tests/test_memory.py::test_auditing_connector_write_emits_event -x` | Wave 0 |
| MEM-02 | MEMORY_READ event emitted on read | unit | `uv run pytest tests/test_memory.py::test_auditing_connector_read_emits_event -x` | Wave 0 |
| MEM-02 | MEMORY_DELETE event emitted even when key not found (found=false) | unit | `uv run pytest tests/test_memory.py::test_auditing_connector_delete_emits_on_missing -x` | Wave 0 |
| MEM-02 | MEMORY_SEARCH event carries result_count, not values | unit | `uv run pytest tests/test_memory.py::test_auditing_connector_search_emits_event -x` | Wave 0 |
| MEM-02 | MEMORY_WRITE payload distinguishes create vs update (created flag) | unit | `uv run pytest tests/test_memory.py::test_auditing_write_created_flag -x` | Wave 0 |
| MEM-02 | EventType enum contains MEMORY_READ, MEMORY_WRITE, MEMORY_DELETE, MEMORY_SEARCH | unit | `uv run pytest tests/test_memory.py::test_event_type_memory_values -x` | Wave 0 |
| MEM-03 | LocalRuntime() without memory_connector defaults to DictMemoryConnector | unit | `uv run pytest tests/test_memory.py::test_local_runtime_default_connector -x` | Wave 0 |
| MEM-03 | LocalRuntime(memory_connector=X) stores X | unit | `uv run pytest tests/test_memory.py::test_local_runtime_custom_connector -x` | Wave 0 |
| MEM-03 | ctx.memory on ExecutionContext is ScopedMemoryConnector (not raw connector) | unit | `uv run pytest tests/test_memory.py::test_execution_context_memory_accessor -x` | Wave 0 |
| MEM-03 | ctx.memory.write(...) does not store value in RunState | integration | `uv run pytest tests/test_memory.py::test_memory_not_in_run_state -x` | Wave 0 |
| MEM-03 | External backend satisfies protocol without inheriting (structural subtyping) | unit | `uv run pytest tests/test_memory.py::test_external_backend_structural_subtyping -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_memory.py -x`
- **Per wave merge:** `uv run pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_memory.py` — new test file covering all requirements above (does not exist yet)
- [ ] `governai/memory/__init__.py` — new module (does not exist yet)

*(Existing test infrastructure — pytest config, fixtures dir, asyncio.run() pattern — fully covers this phase's needs. No framework installation required.)*

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection — `governai/runtime/secrets.py` (SecretsProvider, RedactingAuditEmitter templates)
- Direct codebase inspection — `governai/runtime/thread_store.py` (InMemoryThreadStore, ThreadRecord templates)
- Direct codebase inspection — `governai/audit/emitter.py` (emit_event() helper signature)
- Direct codebase inspection — `governai/models/common.py` (EventType enum, JSONValue type alias)
- Direct codebase inspection — `governai/runtime/context.py` (ExecutionContext wiring pattern)
- Direct codebase inspection — `governai/runtime/local.py` (LocalRuntime.__init__() secrets wiring pattern)
- Direct codebase inspection — `zeroth/src/zeroth/memory/models.py` (ConnectorScope, scope value names)
- Direct codebase inspection — `zeroth/src/zeroth/memory/connectors.py` (Zeroth MemoryConnector Protocol shape)
- Direct codebase inspection — `governai/pyproject.toml` (Python 3.12 requirement, Pydantic >=2.7,<3)

### Secondary (MEDIUM confidence)
- `.planning/phases/04-memory-layer/04-CONTEXT.md` — all decisions D-01 through D-28 (locked by user)
- `.planning/REQUIREMENTS.md` — MEM-01, MEM-02, MEM-03 requirement text

### Tertiary (LOW confidence)
- None — all findings are grounded in direct codebase inspection or CONTEXT.md locked decisions.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all patterns already established in codebase
- Architecture: HIGH — three direct templates present (SecretsProvider, RedactingAuditEmitter, InMemoryThreadStore); new module follows the same conventions exactly
- Pitfalls: HIGH — pitfalls identified from actual codebase patterns (emit_event() signature requirements, audit-on-error pattern, scope target naming)

**Research date:** 2026-04-06
**Valid until:** 2026-05-06 (stable domain; no external library risk)
