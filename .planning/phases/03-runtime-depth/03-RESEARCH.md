# Phase 3: Runtime Depth - Research

**Researched:** 2026-04-05
**Domain:** Capability enforcement, thread lifecycle, secrets redaction, audit extensions (Python / Pydantic / asyncio)
**Confidence:** HIGH

## Summary

Phase 3 is a pure Python extension of an already well-structured codebase. All four feature clusters (capability enforcement, thread lifecycle, secrets redaction, audit extensions) have exact analogues in Phase 1/2 work: `CapabilityPolicy` mirrors existing policy functions, `ThreadStore` mirrors `InterruptStore`/`RunStore`, `SecretsProvider` follows the established "Protocol + No-Op Default" pattern, and `AuditExtension` is a Pydantic `BaseModel` field addition to `AuditEvent`. No new dependencies are introduced. Every pattern already exists in the codebase and must be followed without deviation.

The only subtlety is the secrets redaction pipeline: `SecretRegistry` is a call-time accumulator that feeds into the emitter's pre-persist scan, and it must be thread-safe (per-runtime scope, used across concurrent tool calls). The audit extension backward compatibility requirement is trivially satisfied by Pydantic's `default_factory=list` — deserialization of v0.2.2 events (which lack the field) produces `extensions=[]` automatically.

**Primary recommendation:** Implement in four independent work tracks matching the four feature clusters. Each track maps to one or two new files plus targeted edits to existing files. All new models are Pydantic `BaseModel`. All new store ABCs are async-first. Zero new dependencies.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Capability Enforcement**
- D-01: Capability check is a built-in policy (CapabilityPolicy) that runs inside PolicyEngine.evaluate() like any other policy. Follows Phase 1 deny pattern — PolicyDecision(allow=False, reason='...').
- D-02: Three-tier grant scoping: global, workflow-scoped, and step-scoped grants via CapabilityGrant(capability, scope=global|workflow|step, target=optional). Matches CAP-02.
- D-03: Grants provided via constructor injection — LocalRuntime receives grants: list[CapabilityGrant] at init. The built-in CapabilityPolicy reads them. Zeroth populates grants from its own RBAC layer.
- D-04: Full diagnostic deny — PolicyDecision lists both required and granted capabilities. E.g., "Missing capability: X. Required: [X, Y]. Granted: [Y, Z]." Matches CAP-03.

**Thread Lifecycle**
- D-05: ThreadStore is a new standalone ABC (like RunStore, InterruptStore). Separate concerns — RunStore manages run state, ThreadStore manages thread lifecycle. Both get Redis and InMemory implementations.
- D-06: Linear transitions with interrupt cycle: created→active→idle→archived, plus active→interrupted→active for interrupt cycles. Invalid transitions raise error. Matches THR-01 states.
- D-07: ThreadRecord.run_ids: list[str] tracks which runs have used the thread (multi-run association). Updated when a run starts on this thread.
- D-08: Thread archival emits a THREAD_ARCHIVED audit event. Audit stream captures lifecycle transitions. Consistent with interrupt event pattern. Matches THR-03 audit trail requirement.

**Secrets Redaction**
- D-09: SecretsProvider is a typing.Protocol with async resolve(key: str) -> str. Follows "Protocol + No-Op Default" pattern — a NullSecretsProvider that raises on any resolve() ships as default. Matches SEC-01.
- D-10: Redaction happens at emitter level (pre-persist). AuditEmitter wraps emit() with a redaction pass — before persisting, scans event payload for known secret values and replaces with [REDACTED].
- D-11: SecretRegistry tracks resolved values. When SecretsProvider.resolve() is called, the resolved value is registered with a SecretRegistry. The emitter's redaction pass scans for all registered values.

**Audit Extensions**
- D-12: AuditEvent gains extensions: list[AuditExtension] field. AuditExtension is a BaseModel with type_key: str + data: dict. Defaults to []. v0.2.2 events deserialize to extensions=[] without error.
- D-13: Extensions validated at emit time — AuditExtension is a Pydantic model, validated on construction. Bad data fails immediately. Matches AUD-02.
- D-14: Consumer registration via BaseModel subclass pattern. Consumers define AuditExtension subclasses with a fixed type_key discriminator. No central registry needed.
- D-15: Emitters serialize extensions transparently via model_dump() on the full AuditEvent. Pydantic handles serialization/deserialization. Zero extra code in emitter implementations. Matches AUD-03.

### Claude's Discretion
- ThreadRecord field design beyond status, thread_id, run_ids (created_at, updated_at, metadata, etc.)
- SecretRegistry scope (per-run vs per-runtime) and thread-safety approach
- CapabilityPolicy registration mechanism (auto-registered if grants provided, or explicit)
- Thread state transition validation implementation (enum-based allowed map vs explicit checks)
- Exact EventType enum values for new thread lifecycle events
- NullSecretsProvider error message when resolve() is called without a real provider

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CAP-01 | Tools and agents declare required capabilities; policy engine checks grants before execution | CapabilityPolicy plugs into PolicyEngine.evaluate() using existing PolicyFunc type; Tool.capabilities already populated |
| CAP-02 | CapabilityGrant model supports global, workflow-scoped, and step-scoped grants | New Pydantic BaseModel: CapabilityGrant(capability, scope, target=None); scope is a Literal or Enum |
| CAP-03 | Missing capability produces a deny decision with diagnostic listing required vs granted | PolicyDecision(allow=False, reason=f"Missing capability: {missing}. Required: {required}. Granted: {granted}") |
| SEC-01 | SecretsProvider protocol defines resolve(key) -> str for late-bound secret resolution | typing.Protocol with runtime_checkable; NullSecretsProvider raises KeyError or NotImplementedError |
| SEC-02 | ExecutionContext receives an optional SecretsProvider; tools access secrets at call time | Add secrets_provider parameter to ExecutionContext.__init__; expose as async resolve_secret(key) method |
| SEC-03 | AuditEmitter applies redaction pass — known secret values replaced with [REDACTED] before persistence | Wrapping emit() in AuditEmitter ABC or a RedactingAuditEmitter wrapper; SecretRegistry provides known values |
| AUD-01 | AuditEvent carries a typed extensions field for consumer-provided metadata | Add extensions: list[AuditExtension] = Field(default_factory=list) to AuditEvent Pydantic model |
| AUD-02 | AuditExtensionProtocol defines how extensions are registered and serialized | AuditExtension is a Pydantic BaseModel(type_key: str, data: dict); subclassing provides consumer types |
| AUD-03 | Emitters serialize extensions alongside base event fields transparently | model_dump_json() on AuditEvent already includes all fields including extensions; no emitter changes needed beyond accepting extensions in emit_event() |
| THR-01 | ThreadRecord model tracks lifecycle states (created, active, idle, interrupted, archived) | New Pydantic BaseModel ThreadRecord with status: ThreadStatus (str Enum), thread_id, run_ids, timestamps |
| THR-02 | ThreadStore provides CRUD operations for thread records with status transitions | New ABC ThreadStore with InMemoryThreadStore and RedisThreadStore; transition() method enforces valid state machine |
| THR-03 | Thread archival is a status transition, not deletion — preserves audit trail | ThreadStore.archive() calls transition(thread_id, "archived") and emits THREAD_ARCHIVED event; no delete |
</phase_requirements>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | >=2.7,<3 | All data models (CapabilityGrant, ThreadRecord, AuditExtension) | Project-wide standard; all models use BaseModel |
| python asyncio | stdlib (3.12+) | Async store operations, protocol methods | Project is async-first throughout |
| typing (Protocol, runtime_checkable) | stdlib | SecretsProvider protocol definition | Established pattern in codebase (see ThreadAwareRunStore Protocol) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| redis.asyncio | >=5.0.0 | RedisThreadStore backend | When Redis backends are needed (same as RedisRunStore/RedisInterruptStore) |
| hashlib.blake2b | stdlib | Schema fingerprint | Already used in tools; not needed in Phase 3 but pattern reference |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| typing.Protocol for SecretsProvider | ABC | Protocol allows duck typing and third-party injection without import coupling; codebase uses both — Protocol is correct here per D-09 and established pattern |
| Pydantic BaseModel for AuditExtension | dataclass | Pydantic gives free validation, serialization, and schema — mandatory for extension data |
| Enum-based state machine map for ThreadStatus | explicit if/elif chains | Enum map is O(1) lookup, declaratively documents allowed transitions, and is easily tested; project already uses str Enums |

**Installation:** No new packages required. All dependencies already present.

---

## Architecture Patterns

### Recommended Project Structure

New files to create:
```
governai/
├── policies/
│   └── capability.py      # CapabilityPolicy + CapabilityGrant model
├── runtime/
│   └── thread_store.py    # ThreadRecord + ThreadStatus + ThreadStore ABC + InMemory + Redis impls
├── runtime/
│   └── secrets.py         # SecretsProvider Protocol + NullSecretsProvider + SecretRegistry
└── models/
    └── audit.py           # (edit) add AuditExtension + extensions field
```

Edits to existing files:
```
governai/models/audit.py         # Add AuditExtension BaseModel + extensions: list[AuditExtension]
governai/models/common.py        # Add EventType values: THREAD_CREATED, THREAD_ACTIVE, THREAD_IDLE,
                                 #   THREAD_INTERRUPTED, THREAD_ARCHIVED, CAPABILITY_DENIED
governai/audit/emitter.py        # Add extensions param to emit_event(); add redaction logic
governai/runtime/context.py      # Add secrets_provider: SecretsProvider parameter
governai/runtime/local.py        # Add grants, secrets_provider, thread_store parameters
governai/policies/engine.py      # Auto-register CapabilityPolicy when grants provided
```

### Pattern 1: CapabilityGrant + CapabilityPolicy (CAP-01, CAP-02, CAP-03)

**What:** `CapabilityGrant` is a Pydantic `BaseModel`. `CapabilityPolicy` is a plain function matching `PolicyFunc` that captures a list of grants in its closure (or is a callable class).

**When to use:** Registered as a built-in policy in `PolicyEngine` when `LocalRuntime` is initialized with a non-empty grants list (D-03 via discretion: auto-register when grants provided, or always register to allow empty-grants passthrough).

**Key insight from reading PolicyEngine:** `PolicyEngine.evaluate()` calls `run_policy()` (not `_run_policy_isolated()`). For capability enforcement, the capability policy should use `_run_policy_isolated` just like other policies are intended to use (the engine currently uses `run_policy` — review whether capability policy needs isolation or not; existing tests suggest `run_policy` is the current production path in `evaluate()`).

**Reading the code:** `PolicyContext.capabilities` already contains `list[str]` — the tool's declared required capabilities flow into the context. The CapabilityPolicy reads `ctx.capabilities` (required) and compares against the grants for the current `ctx.workflow_name` and `ctx.step_name`.

```python
# Source: governai/models/policy.py (existing) + new capability.py
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel
from governai.models.policy import PolicyContext, PolicyDecision

GrantScope = Literal["global", "workflow", "step"]

class CapabilityGrant(BaseModel):
    capability: str
    scope: GrantScope = "global"
    target: str | None = None  # workflow_name for workflow scope, step_name for step scope

def make_capability_policy(grants: list[CapabilityGrant]):
    """Return a PolicyFunc that checks required capabilities against provided grants."""
    def capability_policy(ctx: PolicyContext) -> PolicyDecision:
        granted: set[str] = set()
        for grant in grants:
            if grant.scope == "global":
                granted.add(grant.capability)
            elif grant.scope == "workflow" and grant.target == ctx.workflow_name:
                granted.add(grant.capability)
            elif grant.scope == "step" and grant.target == ctx.step_name:
                granted.add(grant.capability)
        required = set(ctx.capabilities)
        missing = required - granted
        if missing:
            missing_str = ", ".join(sorted(missing))
            required_str = ", ".join(sorted(required))
            granted_str = ", ".join(sorted(granted))
            return PolicyDecision(
                allow=False,
                reason=f"Missing capability: {missing_str}. Required: [{required_str}]. Granted: [{granted_str}].",
            )
        return PolicyDecision(allow=True)
    capability_policy.__name__ = "capability_policy"
    return capability_policy
```

### Pattern 2: ThreadStore ABC (THR-01, THR-02, THR-03)

**What:** New `ThreadStatus` (str Enum), `ThreadRecord` (Pydantic BaseModel), `ThreadStore` ABC. Follows `InterruptStore` exactly: ABC with async abstract methods, `InMemoryThreadStore`, `RedisThreadStore`.

**When to use:** `ThreadStore` is injected into `LocalRuntime` at init time (optional, defaults to `InMemoryThreadStore`).

**State machine transitions (from D-06):**
```
ALLOWED_TRANSITIONS = {
    "created":      {"active"},
    "active":       {"idle", "interrupted"},
    "interrupted":  {"active"},
    "idle":         {"active", "archived"},
    "archived":     set(),  # terminal
}
```

Invalid transitions raise a typed error (e.g., `ThreadTransitionError(ValueError)`).

**ThreadRecord fields (discretion items):**
- Required by decisions: `thread_id: str`, `status: ThreadStatus`, `run_ids: list[str]`
- Recommended additions: `created_at: datetime`, `updated_at: datetime`, `metadata: dict[str, Any]`
- Follow `AuditEvent` pattern for `datetime` fields: use `Field(default_factory=_utcnow)`

```python
# Source: established pattern from governai/runtime/run_store.py + interrupts.py
class ThreadStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    IDLE = "idle"
    ARCHIVED = "archived"

class ThreadRecord(BaseModel):
    thread_id: str
    status: ThreadStatus = ThreadStatus.CREATED
    run_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

**ThreadStore ABC methods (minimum viable for THR-02):**
- `async create(thread_id: str) -> ThreadRecord`
- `async get(thread_id: str) -> ThreadRecord | None`
- `async transition(thread_id: str, new_status: ThreadStatus) -> ThreadRecord`
- `async add_run_id(thread_id: str, run_id: str) -> ThreadRecord`
- `async archive(thread_id: str) -> ThreadRecord` (calls `transition` to ARCHIVED)

### Pattern 3: SecretsProvider Protocol + SecretRegistry (SEC-01, SEC-02, SEC-03)

**What:** `SecretsProvider` is a `typing.Protocol` with `async resolve(key: str) -> str`. `SecretRegistry` is a plain class (not a Protocol) that accumulates resolved secret values. The registry is per-runtime scope (not per-run) — simpler, and a tool call within a run always contributes to the same registry.

**Thread-safety for SecretRegistry:** The registry stores resolved values in a `set[str]`. Python's GIL makes simple set operations on CPython effectively thread-safe for add/contains. For async concurrency (which is the real concern here), asyncio is single-threaded — no lock needed. Add a note in docstring.

**Redaction pass:** `AuditEmitter` gains a `_redact(event: AuditEvent) -> AuditEvent` helper that serializes the payload to a JSON string, scans for all registered secret values (replacing each occurrence with `[REDACTED]`), then deserializes back. Alternatively, operate directly on the `payload` dict (dict walk). The string-replace approach is simpler and handles nested structures without recursive walking.

```python
# Source: established typing.Protocol pattern — governai/runtime/run_store.py (ThreadAwareRunStore)
from typing import Protocol, runtime_checkable

@runtime_checkable
class SecretsProvider(Protocol):
    async def resolve(self, key: str) -> str:
        """Resolve a secret by key. Raises KeyError if not found."""
        ...

class NullSecretsProvider:
    """Default no-op provider. Raises on any resolve() call."""
    async def resolve(self, key: str) -> str:
        raise KeyError(
            f"No SecretsProvider configured. Cannot resolve secret '{key}'. "
            "Inject a SecretsProvider into LocalRuntime to enable secret resolution."
        )

class SecretRegistry:
    """Accumulates resolved secret values for emitter-level redaction."""
    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, value: str) -> None:
        """Record a resolved secret value for redaction scanning."""
        if value:  # never register empty string
            self._values.add(value)

    def redact(self, text: str) -> str:
        """Replace all known secret values in text with [REDACTED]."""
        for secret in self._values:
            text = text.replace(secret, "[REDACTED]")
        return text
```

**ExecutionContext change:** Add `secrets_provider: SecretsProvider | None = None`. Expose as an async method so tools call `await ctx.resolve_secret("key")` — this calls `secrets_provider.resolve(key)` and registers the returned value with the `SecretRegistry`.

**Emitter redaction:** The cleanest approach is a `RedactingAuditEmitter` wrapper that wraps any `AuditEmitter` and intercepts `emit()`, running the redaction pass before delegating. This keeps `InMemoryAuditEmitter` and `RedisAuditEmitter` unchanged (D-15 says zero extra emitter code). The `LocalRuntime` wraps its configured emitter with `RedactingAuditEmitter` when a `SecretsProvider` is configured.

### Pattern 4: AuditExtension + AuditEvent.extensions (AUD-01, AUD-02, AUD-03)

**What:** `AuditExtension` is a `BaseModel` with `type_key: str` and `data: dict[str, Any]`. Added as `extensions: list[AuditExtension] = Field(default_factory=list)` to `AuditEvent`.

**Backward compatibility:** Pydantic v2 `model_validate_json()` ignores missing fields that have `default_factory`. A v0.2.2 JSON payload without an `extensions` key deserializes to `extensions=[]`. Verified by existing fixture pattern in `tests/fixtures/run_state_v022.json` which has `"some_future_field": "should_be_ignored"` — Pydantic silently ignores unknown fields by default.

**emit_event() helper:** Add `extensions: list[AuditExtension] | None = None` parameter. Pass through to `AuditEvent(...)`.

```python
# Source: governai/models/audit.py (to be edited)
class AuditExtension(BaseModel):
    type_key: str
    data: dict[str, Any] = Field(default_factory=dict)

class AuditEvent(BaseModel):
    event_id: str
    timestamp: datetime = Field(default_factory=_utcnow)
    run_id: str
    thread_id: str | None = None
    workflow_name: str
    step_name: str | None = None
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    extensions: list[AuditExtension] = Field(default_factory=list)  # NEW
```

### Anti-Patterns to Avoid

- **Deleting ThreadRecords on archival:** Archival is `transition(thread_id, "archived")` — a status change. The `delete()` method on `ThreadStore` (if provided) must never be called for archival. Per REQUIREMENTS.md: "Thread hard deletion — Loses audit trail" is explicitly out of scope.
- **Storing secrets in payload before redaction:** Tools must call `ctx.resolve_secret()` (which registers with SecretRegistry) rather than directly calling `secrets_provider.resolve()`. Direct calls bypass registration and the value won't be redacted.
- **Per-run SecretRegistry:** A per-run registry requires passing it through the full call stack. Per-runtime scope is simpler and correct for the asyncio single-process model.
- **Central extension registry:** D-14 explicitly rejects a central registry. Consumers subclass `AuditExtension` — no registration step.
- **Using run_policy() instead of _run_policy_isolated() for CapabilityPolicy:** The current `PolicyEngine.evaluate()` uses `run_policy()` (no isolation). The capability policy is simple and synchronous — it doesn't need isolation. Match the current engine behavior, don't change evaluate() to use `_run_policy_isolated()` unless that's explicitly a Phase 3 change (it is not).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON serialization of nested models | Custom serializer | `model_dump_json()` / `model_validate_json()` | Pydantic v2 handles nested BaseModel, datetime, Enum, list — all present in new models |
| State machine validation | Complex if/elif chains | Dict-based allowed-transitions map | O(1) lookup, single source of truth, easy to test |
| Async Redis client lazy init | Eager client creation | Pattern from `RedisRunStore._client()` — lazy via `self._redis` cache | Identical pattern in every existing Redis class; copy exactly |
| Secret value scanning | Regex engine | Simple `str.replace()` in a loop | Secrets are exact strings, not patterns; `str.replace()` is O(n*m) but correct and simple |
| Protocol runtime checking | `isinstance` with class | `typing.runtime_checkable` + `isinstance` | Already used for `ThreadAwareRunStore` in run_store.py |

**Key insight:** Every new component in this phase has a direct structural twin in the existing codebase. Copy the twin's structure, adapt to the new domain. Do not invent new patterns.

---

## Common Pitfalls

### Pitfall 1: CapabilityPolicy Step-Scope Target Ambiguity
**What goes wrong:** Step-scoped grants use `target: str` as the step name, but `PolicyContext.step_name` is the step name. If the policy compares `grant.target == ctx.step_name`, it works. If someone assumes `target` is a workflow-scoped step reference like `"workflow.step"`, it silently never matches.
**Why it happens:** The `CapabilityGrant.target` field purpose is ambiguous without a docstring.
**How to avoid:** Document clearly: for `scope="step"`, `target` is the bare step name matching `ctx.step_name`. For `scope="workflow"`, `target` is the workflow name matching `ctx.workflow_name`.
**Warning signs:** Tests that grant a step-scoped capability but the policy still denies.

### Pitfall 2: Redaction Leaves Secrets in extensions.data
**What goes wrong:** The redaction pass operates on `event.payload` dict (as a JSON string), but `extensions[].data` is also a dict that could contain secret values if a consumer injects them.
**Why it happens:** AuditEvent serialization includes `extensions` in `model_dump_json()` output, but a payload-only redaction scan misses nested extension data.
**How to avoid:** The redaction pass must operate on the full `model_dump_json()` output of the entire event (not just `payload`), then reconstruct the event from the redacted JSON string. This catches secrets in any field.
**Warning signs:** A secret value appears in a persisted event's `extensions[0].data`.

### Pitfall 3: v0.2.2 Fixture Test Breaks If extensions Has no Default
**What goes wrong:** Adding `extensions: list[AuditExtension]` without `Field(default_factory=list)` causes `ValidationError` when deserializing old events that lack the field.
**Why it happens:** Pydantic v2 requires fields without defaults to be present in input data.
**How to avoid:** Always use `Field(default_factory=list)` for new list fields on existing models. The `run_state_v022.json` fixture tests this pattern for `RunState` — apply the same practice.
**Warning signs:** Test deserializing an AuditEvent fixture JSON without `extensions` key raises `ValidationError`.

### Pitfall 4: ThreadStore.transition() Called Concurrently
**What goes wrong:** Two concurrent coroutines call `transition(thread_id, "active")` from different runs on the same thread. The InMemory implementation has no CAS — both succeed, leaving state indeterminate.
**Why it happens:** In-memory stores don't guard against async interleaving (asyncio yields at `await` points).
**How to avoid:** `InMemoryThreadStore.transition()` should check the current status at the start of the method and raise `ThreadTransitionError` if the transition is invalid. Since asyncio is single-threaded (no `await` between read and write in the method body), this is safe without locks.
**Warning signs:** Tests that run concurrent transitions and check final state get unexpected results.

### Pitfall 5: PolicyEngine.evaluate() Does Not Auto-Register CapabilityPolicy
**What goes wrong:** Grants are provided to `LocalRuntime` but the capability check never runs because no one registered `CapabilityPolicy` with the engine.
**Why it happens:** Registration is opt-in via `policy_engine.register()`. If the auto-registration logic in `LocalRuntime.__init__()` is missed, capability checks silently never execute.
**How to avoid:** `LocalRuntime.__init__()` registers `capability_policy` automatically when `grants` is non-empty (or always, as a passthrough that approves everything when grants is empty — simpler invariant).
**Warning signs:** A tool with `capabilities=["dangerous_op"]` runs without a grant and is not denied.

---

## Code Examples

Verified patterns from official sources (codebase):

### ThreadStatus Enum (follows RunStatus pattern)
```python
# Source: governai/models/common.py (existing RunStatus pattern)
class ThreadStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    INTERRUPTED = "interrupted"
    IDLE = "idle"
    ARCHIVED = "archived"

ALLOWED_THREAD_TRANSITIONS: dict[ThreadStatus, set[ThreadStatus]] = {
    ThreadStatus.CREATED:      {ThreadStatus.ACTIVE},
    ThreadStatus.ACTIVE:       {ThreadStatus.IDLE, ThreadStatus.INTERRUPTED},
    ThreadStatus.INTERRUPTED:  {ThreadStatus.ACTIVE},
    ThreadStatus.IDLE:         {ThreadStatus.ACTIVE, ThreadStatus.ARCHIVED},
    ThreadStatus.ARCHIVED:     set(),
}
```

### InMemoryThreadStore.transition() (follows InMemoryInterruptStore pattern)
```python
# Source: governai/runtime/interrupts.py (InMemoryInterruptStore pattern)
async def transition(self, thread_id: str, new_status: ThreadStatus) -> ThreadRecord:
    record = self._records.get(thread_id)
    if record is None:
        raise KeyError(f"Unknown thread_id: {thread_id}")
    allowed = ALLOWED_THREAD_TRANSITIONS[record.status]
    if new_status not in allowed:
        raise ThreadTransitionError(
            f"Invalid transition for thread {thread_id}: {record.status} -> {new_status}"
        )
    record.status = new_status
    record.updated_at = _utcnow()
    return record.model_copy(deep=True)
```

### AuditEmitter redaction wrapper
```python
# Source: governai/audit/emitter.py (AuditEmitter ABC pattern)
class RedactingAuditEmitter(AuditEmitter):
    """Wraps another emitter, applying secret redaction before persistence."""
    def __init__(self, inner: AuditEmitter, registry: SecretRegistry) -> None:
        self._inner = inner
        self._registry = registry

    async def emit(self, event: AuditEvent) -> None:
        redacted_json = self._registry.redact(event.model_dump_json())
        redacted_event = AuditEvent.model_validate_json(redacted_json)
        await self._inner.emit(redacted_event)
```

### emit_event() with extensions
```python
# Source: governai/audit/emitter.py (existing emit_event helper)
async def emit_event(
    emitter: AuditEmitter,
    *,
    run_id: str,
    thread_id: str | None = None,
    workflow_name: str,
    event_type: EventType,
    step_name: str | None = None,
    payload: dict[str, Any] | None = None,
    extensions: list[AuditExtension] | None = None,  # NEW
) -> AuditEvent:
    event = AuditEvent(
        event_id=str(uuid.uuid4()),
        run_id=run_id,
        thread_id=thread_id,
        workflow_name=workflow_name,
        step_name=step_name,
        event_type=event_type,
        payload=payload or {},
        extensions=extensions or [],  # NEW
    )
    await emitter.emit(event)
    return event
```

### New EventType values (follows existing enum pattern)
```python
# Source: governai/models/common.py (existing EventType enum)
# Add to EventType:
THREAD_CREATED = "thread_created"
THREAD_ACTIVE = "thread_active"
THREAD_INTERRUPTED = "thread_interrupted"
THREAD_IDLE = "thread_idle"
THREAD_ARCHIVED = "thread_archived"
CAPABILITY_DENIED = "capability_denied"
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| sync redis.Redis | redis.asyncio | Phase 1 (INT-03) | All new Redis stores must use `redis.asyncio` |
| Blocking interrupt manager | async InterruptStore ABC | Phase 1 | ThreadStore follows same async-first design |
| No capability model | Tool.capabilities: list[str] exists | Phase 1/2 | CAP-01 builds on existing field; no schema change to Tool |

**Deprecated/outdated:**
- `blocking_io/_call_interrupt_manager`: Removed in Phase 1 (clean break) — do not reference.
- `run_policy()` in engine: `evaluate()` currently uses `run_policy()` not `_run_policy_isolated()` — Phase 3 does not change this. CapabilityPolicy is registered like any other policy and runs through the current `run_policy()` path.

---

## Open Questions

1. **CapabilityPolicy registration: always-register vs grants-only**
   - What we know: D-03 says "LocalRuntime receives grants"; discretion says "auto-registered if grants provided, or explicit"
   - What's unclear: If grants=[] (empty list), should the capability policy still run (trivially allow everything) or be skipped?
   - Recommendation: Always register when `grants` parameter is provided (even if empty list). A tool with no declared capabilities passes trivially. A tool with declared capabilities and empty grants list is correctly denied. This is the safest invariant.

2. **SecretRegistry scope: per-runtime vs per-run**
   - What we know: Discretion item; per-runtime is simpler; asyncio is single-threaded
   - What's unclear: In a multi-run concurrent scenario (two runs executing simultaneously on same runtime), secrets from run A could theoretically redact unrelated text in run B's audit events
   - Recommendation: Per-runtime scope with a note that this is intentionally conservative (extra redaction is safe; missing redaction is a regulatory violation). Document in docstring.

3. **ThreadStore injection into LocalRuntime vs standalone**
   - What we know: D-05 says ThreadStore is standalone ABC; D-03 says LocalRuntime receives it
   - What's unclear: Does LocalRuntime need to emit audit events on thread transitions (THREAD_ARCHIVED per D-08), which means it needs both an emitter and thread store?
   - Recommendation: Yes — `LocalRuntime` should have `archive_thread(thread_id)` method that calls `thread_store.archive()` and emits `THREAD_ARCHIVED`. This wires the two together at the runtime layer.

---

## Environment Availability

Step 2.6: SKIPPED — Phase 3 is purely code additions and edits with no new external dependencies. All required packages (pydantic, redis) are already in pyproject.toml and available.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/test_policy_checks.py tests/test_audit_events.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAP-01 | Tool with required capability + no grant → PolicyDeniedError before execution | unit | `pytest tests/test_capability_policy.py -x` | ❌ Wave 0 |
| CAP-02 | CapabilityGrant with scope=global/workflow/step matches correctly | unit | `pytest tests/test_capability_policy.py::test_grant_scoping -x` | ❌ Wave 0 |
| CAP-03 | Deny decision includes missing, required, and granted in reason string | unit | `pytest tests/test_capability_policy.py::test_deny_diagnostic -x` | ❌ Wave 0 |
| SEC-01 | NullSecretsProvider.resolve() raises without configuring a real provider | unit | `pytest tests/test_secrets.py::test_null_provider_raises -x` | ❌ Wave 0 |
| SEC-02 | Tool accesses secret via ctx.resolve_secret() at call time | unit | `pytest tests/test_secrets.py::test_execution_context_resolve -x` | ❌ Wave 0 |
| SEC-03 | Secret value resolved at call time never appears in persisted audit event payload | unit | `pytest tests/test_secrets.py::test_redaction_pass -x` | ❌ Wave 0 |
| AUD-01 | AuditEvent with extensions field serializes/deserializes with typed payload | unit | `pytest tests/test_audit_extensions.py::test_extensions_roundtrip -x` | ❌ Wave 0 |
| AUD-02 | Invalid AuditExtension data raises ValidationError at construction | unit | `pytest tests/test_audit_extensions.py::test_extension_validation -x` | ❌ Wave 0 |
| AUD-03 | v0.2.2-era AuditEvent JSON (no extensions key) deserializes to extensions=[] | unit | `pytest tests/test_audit_extensions.py::test_v022_backward_compat -x` | ❌ Wave 0 |
| THR-01 | ThreadRecord model validates all five status values | unit | `pytest tests/test_thread_store.py::test_thread_record_model -x` | ❌ Wave 0 |
| THR-02 | ThreadStore transitions: valid path succeeds, invalid transition raises | unit | `pytest tests/test_thread_store.py::test_transitions -x` | ❌ Wave 0 |
| THR-03 | archive() is a status transition to archived, record still retrievable after | unit | `pytest tests/test_thread_store.py::test_archival_preserves_record -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_capability_policy.py tests/test_thread_store.py tests/test_secrets.py tests/test_audit_extensions.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_capability_policy.py` — covers CAP-01, CAP-02, CAP-03
- [ ] `tests/test_thread_store.py` — covers THR-01, THR-02, THR-03
- [ ] `tests/test_secrets.py` — covers SEC-01, SEC-02, SEC-03
- [ ] `tests/test_audit_extensions.py` — covers AUD-01, AUD-02, AUD-03

All four test files are new. The test framework (pytest 8.x) is already installed and configured. No conftest changes required — existing test patterns use `asyncio.run()` directly without pytest-asyncio fixtures.

---

## Project Constraints (from CLAUDE.md)

CLAUDE.md does not exist in this repository. No project-specific CLAUDE.md directives to enforce. Standard codebase conventions observed from source reading apply instead:

- All files use `from __future__ import annotations` at the top
- All new models: `class Foo(BaseModel):` with Pydantic v2
- All async methods in stores use `async def`
- Redis stores follow lazy-init `_client()` pattern exactly
- `model_copy(deep=True)` for all returned store records (defensive copying)
- `from __future__ import annotations` + type hints as strings where needed to avoid circular imports (lazy imports in `to_manifest()` pattern)
- Tests use `asyncio.run()` wrapper, not `@pytest.mark.asyncio`
- New EventType values follow lowercase snake_case string values
- Store ABCs in same file as InMemory + Redis impls (see `run_store.py`, `interrupts.py`)

---

## Sources

### Primary (HIGH confidence)
- `governai/policies/engine.py` — PolicyEngine.evaluate(), run_policy() flow, registration pattern
- `governai/policies/base.py` — PolicyFunc type, _run_policy_isolated, run_policy
- `governai/models/policy.py` — PolicyContext with capabilities field, PolicyDecision pattern
- `governai/runtime/run_store.py` — RunStore ABC, InMemoryRunStore, RedisRunStore (ThreadStore follows this exactly)
- `governai/runtime/interrupts.py` — InterruptStore ABC, InMemoryInterruptStore, RedisInterruptStore
- `governai/models/audit.py` — AuditEvent model structure to be extended
- `governai/audit/emitter.py` — AuditEmitter ABC, emit_event() helper
- `governai/audit/memory.py` — InMemoryAuditEmitter (simple emit to list)
- `governai/audit/redis.py` — RedisAuditEmitter (model_dump_json serialization pattern)
- `governai/models/common.py` — EventType enum, RunStatus pattern for ThreadStatus
- `governai/runtime/context.py` — ExecutionContext (receives secrets_provider)
- `governai/tools/base.py` — Tool.capabilities field (source of required capabilities)
- `tests/fixtures/run_state_v022.json` — v0.2.2 deserialization fixture pattern
- `tests/test_policy_checks.py` — Policy test patterns to extend
- `pyproject.toml` — python>=3.12, pydantic>=2.7,<3, redis>=5.0.0

### Secondary (MEDIUM confidence)
- `governai/runtime/run_store.py` ThreadAwareRunStore Protocol — confirms `typing.Protocol` + `runtime_checkable` pattern used for injectable dependencies in this codebase

### Tertiary (LOW confidence)
- None — all findings verified directly from source code.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — read directly from pyproject.toml and all imports
- Architecture: HIGH — every pattern copied from existing code with direct file references
- Pitfalls: HIGH — derived from reading actual implementation details (redaction scope, transition race, registration gap)
- Test map: HIGH — test framework verified from pyproject.toml; test files listed are new (Wave 0 gaps)

**Research date:** 2026-04-05
**Valid until:** Stable — no external dependencies change. Valid until codebase refactoring touches the canonical reference files.
