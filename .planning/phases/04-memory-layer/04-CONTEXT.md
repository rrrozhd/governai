# Phase 4: Memory Layer - Context

**Gathered:** 2026-04-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Agents read and write scoped memory through a governed MemoryConnector protocol that emits typed audit events for all operations and ships a working in-memory default backend. Memory data is never stored in RunState — the runtime holds references only.

</domain>

<decisions>
## Implementation Decisions

### Scope Model
- **D-01:** Explicit scope argument — tools pass a MemoryScope enum (run/thread/shared) to each read/write/delete/search call. Mirrors Zeroth's ConnectorScope naming for migration alignment.
- **D-02:** Scope names align with Zeroth: `run`, `thread`, `shared` (not workflow/global as in MEM-01 requirement text). `run` = per-run ephemeral, `thread` = per-conversation, `shared` = global across all runs/threads.
- **D-03:** Auto-fill scope targets from ExecutionContext — thread scope defaults to current thread_id, run scope to current run_id. Explicit target override still available for cross-scope access.
- **D-04:** Cross-scope reads are unrestricted — any scope can read any scope. Writes respect declared scope only.

### Connector Protocol Shape
- **D-05:** MemoryConnector is a `typing.Protocol` (structural subtyping, like SecretsProvider). Not an ABC. Follows PROJECT.md "Protocols over implementations" principle. External backends satisfy the protocol without inheriting.
- **D-06:** Protocol surface: `read(key, scope) -> MemoryEntry | None`, `write(key, value, scope)`, `delete(key, scope)`, `search(query, scope) -> list[MemoryEntry]`. Search is included from day one for RAG/vector DB use cases.
- **D-07:** Async-first — all methods are `async def`. Consistent with GovernAI convention (RunStore, InterruptStore, ThreadStore). Zeroth's sync protocol is its own limitation; GovernAI targets real database backends.
- **D-08:** Key-value data model with JSON payload — `value` is `JSONValue` (dict/list/str/etc). Matches Pydantic patterns.
- **D-09:** `search()` takes a generic `query: dict` parameter — backend interprets query shape. Vector stores use `{'text': ..., 'top_k': ...}`, Postgres uses `{'filter': ...}`. Protocol stays backend-agnostic.
- **D-10:** Single connector per runtime — LocalRuntime receives one MemoryConnector. No named registry at the GovernAI layer. Zeroth composes via its own MemoryConnectorResolver on top.

### MemoryEntry Model
- **D-11:** MemoryEntry carries: `key: str`, `value: JSONValue`, `scope: MemoryScope`, `scope_target: str`, `created_at: datetime`, `updated_at: datetime`, `metadata: dict[str, Any]`. Timestamps for future TTL/LRU. Metadata dict for tags, labels, vector store similarity scores.
- **D-12:** `search()` returns full `list[MemoryEntry]` objects — avoids N+1 read-after-search pattern. Vector stores can put similarity scores in metadata.

### Audit Integration
- **D-13:** AuditingMemoryConnector wrapping pattern — decorates any MemoryConnector and emits audit events. Mirrors RedactingAuditEmitter decorator pattern from Phase 3. Backend authors never deal with audit.
- **D-14:** Four dedicated audit event types: `MEMORY_READ`, `MEMORY_WRITE`, `MEMORY_DELETE`, `MEMORY_SEARCH`. Each is a distinct EventType enum value.
- **D-15:** Audit payload carries key + scope + metadata, no value — memory values could be large or sensitive. Keeps audit lean. Consistent with "references only" principle.
- **D-16:** MEMORY_WRITE payload includes `{created: true/false}` to distinguish create vs update. MEMORY_DELETE payload includes `{found: true/false}` for audit trail of attempted deletes on non-existent keys.
- **D-17:** MEMORY_SEARCH payload carries query (without values) + result_count for audit completeness.
- **D-18:** AuditingMemoryConnector uses `emit_event()` helper — consistent with all other audit emission points. Events flow through the same pipeline (including RedactingAuditEmitter if configured).
- **D-19:** Memory and secrets are separate concerns — AuditingMemoryConnector does NOT register memory values with SecretRegistry. If a tool stores a secret in memory, the secret was already registered when resolved via SecretsProvider.

### Runtime Wiring
- **D-20:** Tools access memory via `ctx.memory` on ExecutionContext — a ScopedMemoryConnector wrapper that knows current thread_id, run_id, workflow_name. Calls auto-resolve scope targets from context.
- **D-21:** AuditingMemoryConnector wrapping happens automatically in LocalRuntime.__init__() when both memory_connector and audit_emitter are present. Mirrors RedactingAuditEmitter auto-wrapping.
- **D-22:** `memory_connector` is an optional parameter on LocalRuntime, like all other injectables. Consistent with secrets_provider, thread_store, run_store patterns.

### Error Handling (Governance-First)
- **D-23:** `read()` on non-existent key returns `None` — this is expected behavior, not an error state.
- **D-24:** `delete()` on non-existent key raises `KeyError` — governance-first approach, every unexpected state is surfaced. Audit event still emitted.
- **D-25:** `write()` is upsert — creates or updates silently. Audit distinguishes create vs update via `{created: true/false}` payload.
- **D-26:** All operations emit audit events regardless of outcome (success, error, not-found).

### DictMemoryConnector
- **D-27:** Nested dict storage: `dict[scope][target][key] -> MemoryEntry`. Natural scope isolation.
- **D-28:** `search()` implementation: key substring match + value text match within scope. Simple but useful for in-memory default. Vector stores override with embedding search.

### Claude's Discretion
- Default memory_connector when none provided to LocalRuntime (DictMemoryConnector vs NullMemoryConnector)
- ScopedMemoryConnector internal design (thin wrapper or full proxy)
- MemoryScope enum placement (models/common.py vs dedicated memory module)
- MemoryEntry Pydantic model field ordering and validation rules
- DictMemoryConnector thread-safety approach (single-threaded asyncio assumption vs locks)
- Exact `connector_type` attribute handling (whether GovernAI protocol includes it like Zeroth or omits it)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Zeroth Memory Module (Migration Alignment)
- `~/coding/zeroth/src/zeroth/memory/connectors.py` — Zeroth's MemoryConnector Protocol (sync, read/write only). GovernAI extends with async + delete + search.
- `~/coding/zeroth/src/zeroth/memory/models.py` — ConnectorScope (run/thread/shared), ConnectorManifest, MemoryContext. Scope names carry into GovernAI.
- `~/coding/zeroth/src/zeroth/memory/registry.py` — InMemoryConnectorRegistry, MemoryConnectorResolver. GovernAI does NOT ship registry/resolver (single connector per runtime).

### GovernAI Audit System
- `governai/audit/emitter.py` — AuditEmitter ABC and emit_event() helper (AuditingMemoryConnector uses this)
- `governai/models/audit.py` — AuditEvent model with extensions field
- `governai/models/common.py` — EventType enum (needs MEMORY_READ, MEMORY_WRITE, MEMORY_DELETE, MEMORY_SEARCH)
- `governai/audit/memory.py` — InMemoryAuditEmitter (test reference)

### GovernAI Secrets (Decorator Pattern Reference)
- `governai/runtime/secrets.py` — SecretsProvider Protocol, SecretRegistry, RedactingAuditEmitter. AuditingMemoryConnector follows same decorator pattern.

### GovernAI Runtime Integration
- `governai/runtime/local.py` — LocalRuntime (receives memory_connector param, auto-wraps with AuditingMemoryConnector)
- `governai/runtime/context.py` — ExecutionContext (gains ctx.memory ScopedMemoryConnector property)

### GovernAI Store Patterns
- `governai/runtime/thread_store.py` — ThreadStore ABC, InMemoryThreadStore (pattern reference for DictMemoryConnector)
- `governai/runtime/run_store.py` — RunStore ABC (store interface conventions)

### Tests
- `tests/test_policy_checks.py` — Existing policy tests (pattern reference)
- `~/coding/zeroth/tests/memory/test_connectors.py` — Zeroth's memory connector tests (alignment reference)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `emit_event()` helper — AuditingMemoryConnector delegates audit emission here
- `RedactingAuditEmitter` — decorator pattern reference for AuditingMemoryConnector
- `SecretsProvider` typing.Protocol — pattern reference for MemoryConnector protocol
- `InMemoryThreadStore` — storage pattern reference for DictMemoryConnector
- `EventType` enum — extend with MEMORY_* values
- `ExecutionContext.resolve_secret()` — pattern for how ctx.memory accessor should work

### Established Patterns
- typing.Protocol for injectable dependencies (SecretsProvider) — MemoryConnector follows
- Decorator/wrapper pattern for cross-cutting concerns (RedactingAuditEmitter) — AuditingMemoryConnector follows
- Auto-wrapping in LocalRuntime.__init__() when dependencies present — memory follows
- Pydantic BaseModel for all data models — MemoryEntry follows
- `model_copy(deep=True)` isolation in store return values
- Async-first on all store/connector interfaces

### Integration Points
- `LocalRuntime.__init__()` — add `memory_connector` optional parameter
- `ExecutionContext.__init__()` — add memory connector + ScopedMemoryConnector wrapper
- `EventType` enum — add `MEMORY_READ`, `MEMORY_WRITE`, `MEMORY_DELETE`, `MEMORY_SEARCH`
- `governai/__init__.py` — export new public types (MemoryConnector, MemoryEntry, MemoryScope, DictMemoryConnector, AuditingMemoryConnector)

</code_context>

<specifics>
## Specific Ideas

- Scope names MUST be `run`, `thread`, `shared` (Zeroth alignment) — not `workflow`/`global` from MEM-01 text
- Zeroth's MemoryConnector is sync; GovernAI's is async. This is intentional divergence — Zeroth wraps GovernAI connectors at its layer
- Search is new capability not in Zeroth's protocol — GovernAI adds it for RAG/vector DB use cases that Zeroth will consume
- No MemoryConnectorRegistry/Resolver at GovernAI layer — Zeroth already has this and GovernAI keeps a simpler single-connector-per-runtime model

</specifics>

<deferred>
## Deferred Ideas

- **MEM-04**: Redis-backed MemoryConnector (v2 requirement)
- **MEM-05**: Vector store MemoryConnector for semantic search (v2 requirement)
- **MEM-06**: Memory retention policies / TTL-based expiry per scope (v2 requirement)
- Named connector registry at GovernAI layer (Zeroth handles this today)

</deferred>

---

*Phase: 04-memory-layer*
*Context gathered: 2026-04-06*
