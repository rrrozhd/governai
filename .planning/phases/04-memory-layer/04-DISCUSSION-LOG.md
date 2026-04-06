# Phase 4: Memory Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-06
**Phase:** 04-memory-layer
**Areas discussed:** Scope model, Connector protocol shape, Audit integration, Runtime wiring, MemoryEntry model, DictMemoryConnector internals, Zeroth migration path, Error handling

---

## Scope Model

### How should memory scope be specified?

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit scope argument | Tool passes scope enum + optional target ID. Mirrors CapabilityGrant three-tier scoping. | ✓ |
| Derived from ExecutionContext | Scope auto-resolved from context. Simpler but less flexible. | |
| You decide | Claude picks. | |

**User's choice:** Explicit scope argument
**Notes:** Clean, predictable. Mirrors Phase 3 pattern.

### Auto-fill scope targets from context?

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-fill from context | Thread scope defaults to current thread_id, workflow to workflow_name. Override allowed. | ✓ |
| Always required | Caller must always pass target ID. | |
| You decide | Claude picks. | |

**User's choice:** Auto-fill from context

### Scope enum values?

| Option | Description | Selected |
|--------|-------------|----------|
| Memory-specific: global/workflow/thread | Thread is natural boundary. Aligns with MEM-01 text. | ✓ (initially) |
| Mirror CapabilityGrant: global/workflow/step | Consistent but step-scoped memory is unusual. | |

**User's choice:** Initially global/workflow/thread, later revised to run/thread/shared (Zeroth alignment).

### Cross-scope reads?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, reads are unrestricted | Any scope can read any scope. Writes respect declared scope. | ✓ |
| Strict isolation | Only read/write within declared scope. | |

**User's choice:** Unrestricted reads

---

## Connector Protocol Shape

### Data model?

| Option | Description | Selected |
|--------|-------------|----------|
| Key-value with JSON payload | read(key, scope) -> entry, write(key, value, scope). Value is JSONValue. | ✓ |
| Document model with metadata | Richer but heavier for v0.3.0. | |

**User's choice:** Key-value with JSON payload

### Operations?

| Option | Description | Selected |
|--------|-------------|----------|
| read/write/delete | Minimal CRUD, no search. | |
| read/write/delete/search | Include search for RAG/vector DB use cases. | ✓ |
| read/write only | Absolute minimum. | |

**User's choice:** read/write/delete/search
**Notes:** User emphasized RAG use cases — vector DBs where search is primary function. Postgres and MongoDB instances also need to be hookable.

### Search parameterization?

| Option | Description | Selected |
|--------|-------------|----------|
| Generic query dict | search(query: dict, scope). Backend interprets. | ✓ |
| Typed SearchQuery model | Structured but bakes in assumptions. | |

**User's choice:** Generic query dict

### Protocol type?

| Option | Description | Selected |
|--------|-------------|----------|
| typing.Protocol | Structural subtyping. Matches SecretsProvider. | ✓ |
| ABC | Nominal subtyping. Matches ThreadStore/RunStore. | |

**User's choice:** typing.Protocol

---

## Audit Integration

### Audit event payload content?

| Option | Description | Selected |
|--------|-------------|----------|
| Key + scope + metadata, no value | Keeps audit lean, avoids data exposure. | ✓ |
| Key + scope + value hash | Hash for change detection. | |
| Key + scope + full value | Maximum traceability but unbounded size. | |

**User's choice:** Key + scope + metadata, no value

### Where audit events are emitted?

| Option | Description | Selected |
|--------|-------------|----------|
| Wrapping layer (AuditingMemoryConnector) | Decorator pattern like RedactingAuditEmitter. | ✓ |
| Inside each implementation | Each backend emits its own events. | |

**User's choice:** Wrapping layer

### MEMORY_DELETE event type?

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated MEMORY_DELETE event | Clean separation in audit stream. | ✓ |
| Reuse MEMORY_WRITE + flag | Fewer EventType values. | |

**User's choice:** Dedicated event

### MEMORY_SEARCH event type?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, MEMORY_SEARCH event | Audit completeness. Payload: query + result_count. | ✓ |
| No, skip search auditing | Less audit volume. | |

**User's choice:** Dedicated MEMORY_SEARCH event

### Interaction with RedactingAuditEmitter?

| Option | Description | Selected |
|--------|-------------|----------|
| No, separate concerns | Memory values are not secrets by default. | ✓ |
| Yes, register values | Defense in depth but over-redacts. | |

**User's choice:** Separate concerns

### Event emission mechanism?

| Option | Description | Selected |
|--------|-------------|----------|
| Use emit_event() helper | Consistent with all other audit points. | ✓ |
| Direct AuditEvent construction | More control but duplicates logic. | |

**User's choice:** emit_event() helper

---

## Runtime Wiring

### How tools access memory?

| Option | Description | Selected |
|--------|-------------|----------|
| Via ExecutionContext | ctx.memory property with ScopedMemoryConnector wrapper. | ✓ |
| Direct connector injection | Tool receives MemoryConnector as parameter. | |

**User's choice:** Via ExecutionContext (ctx.memory)

### AuditingMemoryConnector wrapping?

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-wrap in LocalRuntime | Automatic if emitter present. | ✓ |
| Caller wraps explicitly | More control but error-prone. | |

**User's choice:** Auto-wrap in LocalRuntime

### Default when no connector provided?

**User's choice:** You decide (Claude's discretion)

### ctx.memory API style?

| Option | Description | Selected |
|--------|-------------|----------|
| Expose connector object (ctx.memory) | ctx.memory.read(key, scope). Cleaner delegation. | ✓ |
| Direct methods on context | ctx.memory_read(). Flatter but adds methods. | |

**User's choice:** Expose connector object

### Scope auto-fill location?

| Option | Description | Selected |
|--------|-------------|----------|
| Scope-aware wrapper (ScopedMemoryConnector) | ctx.memory knows current thread_id/run_id. | ✓ |
| Tools pass scope + target manually | Verbose and error-prone. | |

**User's choice:** Scope-aware wrapper

### memory_connector parameter on LocalRuntime?

| Option | Description | Selected |
|--------|-------------|----------|
| Optional | Like all other injectables. | ✓ |

**User's choice:** Optional

---

## MemoryEntry Model

### Fields beyond key and value?

| Option | Description | Selected |
|--------|-------------|----------|
| Key + value + timestamps + metadata dict | Timestamps for TTL/LRU, metadata for tags/labels/similarity scores. | ✓ |
| Key + value + timestamps | Minimal but extensible. | |
| Key + value only | Absolute minimum. | |

**User's choice:** Key + value + timestamps + metadata dict

### search() return type?

| Option | Description | Selected |
|--------|-------------|----------|
| Full MemoryEntry list | Avoids N+1 read-after-search. | ✓ |
| Keys only | Lighter but requires follow-up reads. | |

**User's choice:** Full MemoryEntry list

---

## DictMemoryConnector Internals

### Storage structure?

| Option | Description | Selected |
|--------|-------------|----------|
| Nested dict: scope -> target -> key | Natural scope isolation. | ✓ |
| Flat dict with composite keys | Simpler but requires prefix matching. | |

**User's choice:** Nested dict

### search() implementation?

| Option | Description | Selected |
|--------|-------------|----------|
| Key substring + value text match | Simple but useful for in-memory default. | ✓ |
| Key prefix match only | Minimal coverage. | |

**User's choice:** Key substring + value text match

---

## Zeroth Migration Path

### Scope name alignment?

| Option | Description | Selected |
|--------|-------------|----------|
| Align with Zeroth: run/thread/shared | Easier migration. | ✓ |
| Stick with MEM-01: thread/workflow/global | More descriptive. | |

**User's choice:** Align with Zeroth (overrides earlier global/workflow/thread decision)

### Async vs sync?

| Option | Description | Selected |
|--------|-------------|----------|
| Async (GovernAI convention) | Consistent with all other stores. | ✓ |
| Sync (match Zeroth) | Direct compatibility but breaks convention. | |

**User's choice:** Async

### Registry/resolver?

| Option | Description | Selected |
|--------|-------------|----------|
| Single connector per runtime | Simpler. Zeroth composes on top. | ✓ |
| Named registry like Zeroth | More powerful but premature. | |

**User's choice:** Single connector per runtime

---

## Error Handling

### read() on missing key?

| Option | Description | Selected |
|--------|-------------|----------|
| Return None | Expected behavior, not an error. | ✓ |
| Raise KeyError | More explicit. | |

**User's choice:** Return None

### delete() on missing key?

| Option | Description | Selected |
|--------|-------------|----------|
| Always strict (KeyError) | Governance-first, every unexpected state surfaced. Audit event still emitted. | ✓ |
| No-op, silent | Idempotent. | |

**User's choice:** Always strict — with clear auditability
**Notes:** User clarified: not purely silent. Governance-first approach. KeyError raised + audit event emitted.

### write() overwrite behavior?

| Option | Description | Selected |
|--------|-------------|----------|
| Overwrite silently (upsert) | Simple, matches Zeroth. | ✓ |
| Separate create/update | More explicit but heavier protocol. | |

**User's choice:** Upsert, but audit MUST distinguish create vs update
**Notes:** User clarified: audit event payload includes {created: true/false} for full traceability.

---

## Claude's Discretion

- Default memory_connector when none provided to LocalRuntime
- ScopedMemoryConnector internal design
- MemoryScope enum placement
- MemoryEntry field ordering and validation
- DictMemoryConnector thread-safety approach
- connector_type attribute handling

## Deferred Ideas

- Redis-backed MemoryConnector (MEM-04, v2)
- Vector store MemoryConnector (MEM-05, v2)
- Memory retention policies / TTL (MEM-06, v2)
- Named connector registry at GovernAI layer
