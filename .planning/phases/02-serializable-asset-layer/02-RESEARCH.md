# Phase 2: Serializable Asset Layer - Research

**Researched:** 2026-04-05
**Domain:** Pydantic v2 serialization, Redis WATCH/MULTI/EXEC optimistic locking, Python Protocol patterns
**Confidence:** HIGH

## Summary

Phase 2 adds three independent but related capabilities: (1) AgentSpec — a fully serializable Pydantic model capturing all non-callable fields from Agent, plus a classmethod factory `Agent.from_spec()`; (2) ToolManifest — a read-only serializable descriptor of a Tool including schemas, capabilities, and placement; and (3) atomic persistence for RedisRunStore via WATCH/MULTI/EXEC and epoch-based CAS for InMemoryRunStore.

The codebase is already well-prepared. Phase 1 established all the patterns this phase reuses: `model_json_schema()` for schema extraction, blake2b for fingerprinting, `model_dump_json()` / `model_validate_json()` for serialization, `model_copy(deep=True)` for isolation, and async-first store ABCs. The WATCH/MULTI/EXEC transaction in `redis.asyncio` is available and well-understood — `WatchError` is the conflict signal, raised when `pipe.execute()` detects the watched key changed. The FakeRedis pattern used in existing tests must be extended to support `pipeline()`, `watch()`, `multi()`, and `execute()` for the new atomic-write tests.

GovernedFlowSpec and GovernedStepSpec are pure dataclasses. They gain zero new fields from this phase. RunState's `model_config` is empty (no `extra="forbid"`), so unknown fields are silently ignored — the v0.2.2 fixture will deserialize cleanly without any model changes. The v0.2.2 fixture must be committed as a real JSON file in `tests/fixtures/`.

**Primary recommendation:** Implement in three clean, testable units — AgentSpec/ToolManifest (new files in `governai/agents/spec.py` and `governai/tools/manifest.py`), then atomic persistence refactor in `governai/runtime/run_store.py`, then the v0.2.2 fixture test. Each unit has a clear test surface and no internal dependencies on each other.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**AgentSpec Shape**
- D-01: AgentSpec stores input/output models as JSON Schema dicts (via `model_json_schema()`). Fully serializable. Model reconstruction at `from_spec()` time via a ModelRegistry.
- D-02: Each model reference stored as `{name: str, schema: dict}` pair. The name enables registry-based reconstruction; the schema enables Studio display/validation without loading Python classes.
- D-03: AgentSpec carries `version` (SemVer, default `'0.0.0'`) and `schema_fingerprint` (blake2b, same pattern as Tool from Phase 1). Enables future AgentRegistry keying by `(name, version)`.
- D-04: `allowed_tools` stays as `list[str]` of tool names. Tool resolution happens at `from_spec()` time using ToolRegistry. No version pinning on tool references.
- D-05: `Agent.from_spec(spec, handler, registry=None)` takes the callable handler as required arg and an optional ModelRegistry for resolving input/output model classes by name. Raises if models are needed but registry is None or name not found.
- D-06: ModelRegistry protocol: `resolve(name: str) -> type[BaseModel]`. Simple name-based lookup. No versioning on model resolution.
- D-07: `Agent.to_spec()` is a method on Agent (mirrors `Tool.to_manifest()` pattern). Extraction logic stays close to the source.

**ToolManifest Design**
- D-08: ToolManifest carries all Tool data fields: name, version, description, input/output schemas (as JSON Schema dicts), schema_fingerprint, capabilities, side_effect, timeout_seconds, requires_approval, tags, executor_type, execution_placement, remote_name.
- D-09: ToolManifest is read-only metadata. No `to_tool()` reconstruction path. Tool instances always created from Python code.
- D-10: ToolManifest is usable for capability checks without a live Tool.

**Atomic Persistence**
- D-11: WATCH/MULTI/EXEC transaction boundary includes both the state payload write AND the checkpoint index entry.
- D-12: Optimistic lock conflict triggers retry with exponential backoff (up to 3 retries). Raises typed `StateConcurrencyError` if retries exhausted.
- D-13: PERS-03 validation lives in the store layer. RedisRunStore.put() validates before writing.
- D-14: InMemoryRunStore gets epoch-based compare-and-swap for test parity with Redis atomic semantics.

**Backward Compatibility**
- D-15: AgentSpec and ToolManifest are new standalone models. GovernedFlowSpec/GovernedStepSpec gain no new required fields.
- D-16: v0.2.2 RunState deserialization verified via committed JSON fixture test.

### Claude's Discretion

- Unknown field handling on RunState validation (ignore vs forbid) — decide based on Zeroth's usage pattern and forward-compatibility needs
- Exact retry backoff timing for optimistic lock conflicts
- StateConcurrencyError exception hierarchy placement
- ModelRegistry default implementation (if any ships with GovernAI vs left to consumers)
- Internal structure of the WATCH/MULTI/EXEC pipeline (key patterns, TTL handling within transaction)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SPEC-01 | AgentSpec is a serializable Pydantic model extracting all non-callable fields from Agent | Pydantic BaseModel with JSON Schema dict fields; all Agent.__init__ params except `handler` are serializable |
| SPEC-02 | Agent.from_spec(spec) factory creates a runtime Agent from an AgentSpec | Classmethod factory pattern; ModelRegistry.resolve() rebuilds input/output model types |
| SPEC-03 | AgentSpec is JSON-serializable via model_dump_json() with schemas as JSON Schema dicts | Pydantic v2 model_dump_json() handles dict fields natively; verified working |
| MFST-01 | ToolManifest is a serializable Pydantic model describing a tool without the Python callable | Pydantic BaseModel; Tool has no callable field — all Tool.__init__ params except the execute logic are data |
| MFST-02 | Tool.to_manifest() extracts a ToolManifest from a live Tool instance | Mirror of Agent.to_spec() pattern; schema_fingerprint already computed at registration |
| MFST-03 | ToolManifest carries input/output schemas, capabilities, placement, and version | All fields from Tool.__init__ captured as JSON-serializable types |
| PERS-01 | Runtime persists run state atomically — crash between write and cache never leaves state inconsistent | WATCH/MULTI/EXEC wraps state key write + checkpoint index rpush atomically |
| PERS-02 | RedisRunStore uses optimistic locking (WATCH/MULTI/EXEC) for compare-and-swap writes | redis.asyncio Pipeline.watch() + multi() + execute(); WatchError on conflict |
| PERS-03 | Runtime validates handoff targets, command state updates, and transitions before persisting state | Validation logic in RunStore.put() before WATCH/MULTI/EXEC block |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.12.5 (installed) | AgentSpec, ToolManifest model definitions; round-trip serialization | Already the project standard for all data models; v2 API throughout |
| redis.asyncio | 7.3.0 (installed) | WATCH/MULTI/EXEC atomic writes in RedisRunStore | Already the project's Redis client; Pipeline class provides full optimistic lock support |
| hashlib (stdlib) | stdlib | blake2b fingerprinting for AgentSpec schema_fingerprint | Phase 1 pattern; already used in ToolRegistry |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | stdlib | `json.dumps(..., sort_keys=True)` for deterministic fingerprint input | Same usage as ToolRegistry.register() |
| typing (stdlib) | stdlib | `Protocol`, `runtime_checkable` for ModelRegistry protocol | Matches existing Protocol pattern in run_store.py (ThreadAwareRunStore) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JSON Schema dict storage | Pickle / cloudpickle | JSON Schema is the locked decision; pickle is not network-safe or Studio-compatible |
| WATCH/MULTI/EXEC retry loop | Lua script (EVALSHA) | Lua avoids round-trips but adds Redis scripting dependency; WATCH/MULTI/EXEC is explicit and testable with FakeRedis |
| StateConcurrencyError as standalone | Subclass of RuntimeError | Either works; placement is Claude's discretion |

**Installation:** No new packages required. All dependencies already installed.

**Version verification:** Verified with `.venv/bin/python -c "import pydantic; print(pydantic.__version__)"` → 2.12.5 and `import redis; print(redis.__version__)` → 7.3.0.

---

## Architecture Patterns

### Recommended Project Structure

New files this phase creates:

```
governai/
├── agents/
│   ├── base.py             # Agent — add to_spec() method, from_spec() classmethod
│   ├── spec.py             # NEW: AgentSpec, ModelRegistry protocol, ModelSchemaRef
│   └── registry.py         # AgentRegistry — unchanged
├── tools/
│   ├── base.py             # Tool — add to_manifest() method
│   └── manifest.py         # NEW: ToolManifest
├── runtime/
│   └── run_store.py        # RedisRunStore.put() → WATCH/MULTI/EXEC; InMemoryRunStore CAS; StateConcurrencyError
└── __init__.py             # Export AgentSpec, ToolManifest, StateConcurrencyError

tests/
├── fixtures/
│   └── run_state_v022.json # NEW: v0.2.2 RunState JSON fixture
├── test_agent_spec.py      # NEW
├── test_tool_manifest.py   # NEW
└── test_atomic_run_store.py # NEW
```

### Pattern 1: AgentSpec as Serializable Descriptor

**What:** Pydantic BaseModel that captures every data field from Agent.__init__ except `handler`. Input/output models become `ModelSchemaRef` (name + schema dict). `to_spec()` computes schema fingerprint inline; `from_spec()` resolves model classes via ModelRegistry.

**When to use:** Any time Agent metadata must cross a process boundary, be stored, or be inspected without loading the agent's Python callable.

```python
# governai/agents/spec.py
from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from governai.tools.base import ExecutionPlacement


class ModelSchemaRef(BaseModel):
    """Serializable reference to a Pydantic model by name and JSON Schema."""
    name: str
    schema: dict[str, Any]


@runtime_checkable
class ModelRegistry(Protocol):
    """Consumer-provided registry for resolving model classes by name."""
    def resolve(self, name: str) -> type[BaseModel]: ...


class AgentSpec(BaseModel):
    """Serializable descriptor for an Agent — all non-callable fields."""
    name: str
    description: str
    instruction: str
    version: str = "0.0.0"
    schema_fingerprint: str | None = None
    input_model: ModelSchemaRef
    output_model: ModelSchemaRef
    allowed_tools: list[str]
    allowed_handoffs: list[str]
    max_turns: int = 1
    max_tool_calls: int = 1
    tags: list[str] = []
    requires_approval: bool = False
    capabilities: list[str] = []
    side_effect: bool = False
    executor_type: str = "agent"
    execution_placement: ExecutionPlacement = "local_only"
    remote_name: str | None = None
```

```python
# In governai/agents/base.py — additions to Agent
def to_spec(self) -> "AgentSpec":
    from governai.agents.spec import AgentSpec, ModelSchemaRef
    input_schema = self.input_model.model_json_schema()
    output_schema = self.output_model.model_json_schema()
    combined = json.dumps(
        {"input": input_schema, "output": output_schema}, sort_keys=True
    ).encode()
    fingerprint = hashlib.blake2b(combined, digest_size=16).hexdigest()
    return AgentSpec(
        name=self.name,
        description=self.description,
        instruction=self.instruction,
        version=getattr(self, "version", "0.0.0"),
        schema_fingerprint=fingerprint,
        input_model=ModelSchemaRef(name=self.input_model.__name__, schema=input_schema),
        output_model=ModelSchemaRef(name=self.output_model.__name__, schema=output_schema),
        allowed_tools=list(self.allowed_tools),
        allowed_handoffs=list(self.allowed_handoffs),
        max_turns=self.max_turns,
        max_tool_calls=self.max_tool_calls,
        tags=list(self.tags),
        requires_approval=self.requires_approval,
        capabilities=list(self.capabilities),
        side_effect=self.side_effect,
        executor_type=self.executor_type,
        execution_placement=self.execution_placement,
        remote_name=self.remote_name,
    )

@classmethod
def from_spec(
    cls,
    spec: "AgentSpec",
    handler: "AgentHandler",
    registry: "ModelRegistry | None" = None,
) -> "Agent":
    from governai.agents.spec import ModelRegistry
    if registry is not None:
        input_model = registry.resolve(spec.input_model.name)
        output_model = registry.resolve(spec.output_model.name)
    else:
        # Without registry, cannot reconstruct model classes
        raise ValueError(
            f"ModelRegistry required to reconstruct input/output models for Agent '{spec.name}'"
        )
    return cls(
        name=spec.name,
        description=spec.description,
        instruction=spec.instruction,
        handler=handler,
        input_model=input_model,
        output_model=output_model,
        allowed_tools=spec.allowed_tools,
        allowed_handoffs=spec.allowed_handoffs,
        max_turns=spec.max_turns,
        max_tool_calls=spec.max_tool_calls,
        tags=spec.tags,
        requires_approval=spec.requires_approval,
        capabilities=spec.capabilities,
        side_effect=spec.side_effect,
        execution_placement=spec.execution_placement,
        remote_name=spec.remote_name,
    )
```

**Note on D-05 edge case:** If `registry` is `None`, the decision says "Raises if models are needed but registry is None." This means `from_spec(spec, handler)` without a registry must always raise — there is no code path that reconstructs models without the registry.

### Pattern 2: ToolManifest as Read-Only Tool Descriptor

**What:** Pydantic BaseModel with all Tool data fields. `Tool.to_manifest()` extracts the manifest. No `from_manifest()` — ToolManifest is display/policy metadata only.

**When to use:** Studio display, pre-flight capability checks, policy engine evaluation without loading callables.

```python
# governai/tools/manifest.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from governai.tools.base import ExecutionPlacement


class ToolManifest(BaseModel):
    """Read-only serializable descriptor for a Tool."""
    name: str
    version: str = "0.0.0"
    description: str = ""
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    schema_fingerprint: str | None = None
    capabilities: list[str] = []
    side_effect: bool = False
    timeout_seconds: float | None = None
    requires_approval: bool = False
    tags: list[str] = []
    executor_type: str = "python"
    execution_placement: ExecutionPlacement = "local_only"
    remote_name: str | None = None
```

```python
# In governai/tools/base.py — addition to Tool
def to_manifest(self) -> "ToolManifest":
    from governai.tools.manifest import ToolManifest
    return ToolManifest(
        name=self.name,
        version=self.version,
        description=self.description,
        input_schema=self.input_model.model_json_schema(),
        output_schema=self.output_model.model_json_schema(),
        schema_fingerprint=self.schema_fingerprint,
        capabilities=list(self.capabilities),
        side_effect=self.side_effect,
        timeout_seconds=self.timeout_seconds,
        requires_approval=self.requires_approval,
        tags=list(self.tags),
        executor_type=self.executor_type,
        execution_placement=self.execution_placement,
        remote_name=self.remote_name,
    )
```

### Pattern 3: WATCH/MULTI/EXEC Atomic Write in RedisRunStore

**What:** Replace the current two-step `write_checkpoint()` + `set(key, payload)` in `RedisRunStore.put()` with a WATCH/MULTI/EXEC transaction. WATCH the run key, read current epoch, queue the state write and checkpoint index append inside MULTI/EXEC, retry on WatchError.

**When to use:** Every `RedisRunStore.put()` call.

```python
# In RedisRunStore.put() — refactored
from redis.exceptions import WatchError

async def put(self, state: RunState) -> None:
    # PERS-03: validate before touching Redis
    self._validate_state(state)

    client = await self._client()
    run_key = self._key(state.run_id)
    checkpoint_id = state.checkpoint_id or str(uuid.uuid4())

    retries = 3
    delay = 0.05  # 50ms initial backoff

    for attempt in range(retries + 1):
        async with client.pipeline(transaction=True) as pipe:
            try:
                # WATCH the run key — conflict if another writer changed it
                await pipe.watch(run_key)

                # Read current value to check epoch (optimistic lock)
                raw = await pipe.get(run_key)
                if raw is not None:
                    existing = RunState.model_validate_json(
                        self._decode_text(raw) or "{}"
                    )
                    if existing.epoch >= state.epoch:
                        # Stale write: caller must re-read and retry
                        raise StateConcurrencyError(
                            f"Stale write for run {state.run_id}: "
                            f"store epoch={existing.epoch}, write epoch={state.epoch}"
                        )

                # Queue the atomic writes
                pipe.multi()

                state.checkpoint_id = checkpoint_id
                payload = state.model_dump_json()
                if self.ttl_seconds is None:
                    pipe.set(run_key, payload)
                else:
                    pipe.set(run_key, payload, ex=int(self.ttl_seconds))

                # Checkpoint payload
                cp_key = self._checkpoint_key(checkpoint_id)
                if self.ttl_seconds is None:
                    pipe.set(cp_key, payload)
                else:
                    pipe.set(cp_key, payload, ex=int(self.ttl_seconds))

                # Checkpoint index
                pipe.rpush(
                    self._thread_checkpoint_index_key(state.thread_id),
                    checkpoint_id,
                )

                await pipe.execute()  # raises WatchError on conflict
                break  # success

            except WatchError:
                if attempt >= retries:
                    raise StateConcurrencyError(
                        f"Optimistic lock conflict on run {state.run_id} "
                        f"after {retries} retries"
                    ) from None
                await asyncio.sleep(delay * (2 ** attempt))

    await self._record_thread_run(state.thread_id, state.run_id)
```

**Key insight about the pattern:** `pipe.watch(key)` must be called before `pipe.multi()`. After `watch()`, the pipeline is in immediate-execute mode (commands run instantly). After `multi()`, commands queue until `execute()`. If the watched key changes between `watch()` and `execute()`, `execute()` raises `WatchError`. The pipeline context manager calls `reset()` on exit, which sends UNWATCH.

### Pattern 4: InMemoryRunStore Epoch-Based CAS

**What:** InMemoryRunStore.put() checks the stored epoch against state.epoch before writing. Raises StateConcurrencyError if the stored epoch is >= the incoming epoch.

```python
async def put(self, state: RunState) -> None:
    # PERS-03 validation
    self._validate_state(state)

    existing = self._state.get(state.run_id)
    if existing is not None and existing.epoch >= state.epoch:
        raise StateConcurrencyError(
            f"Stale write for run {state.run_id}: "
            f"store epoch={existing.epoch}, write epoch={state.epoch}"
        )

    checkpoint_id = await self.write_checkpoint(state)
    state.checkpoint_id = checkpoint_id
    self._state[state.run_id] = state.model_copy(deep=True)
    self._record_thread_run(state.thread_id, state.run_id)
```

**Note:** `epoch` is already a field on RunState (current value is `0` by default). The runtime must increment epoch on each state update for CAS to be meaningful. Check whether epoch is currently incremented — if not, the store layer may need to auto-increment before the epoch check, or this is a caller contract.

### Pattern 5: StateConcurrencyError Placement

StateConcurrencyError belongs in `governai/runtime/run_store.py` alongside the stores that raise it. It is a store-layer concern, not a workflow or policy concern.

```python
class StateConcurrencyError(RuntimeError):
    """Raised when an optimistic lock conflict exhausts retries."""
```

This is Claude's discretion per CONTEXT.md. RuntimeError subclass keeps it in Python's standard error hierarchy without pulling in a new base.

### Pattern 6: PERS-03 Validation in store layer

Validation logic lives in a `_validate_state(state: RunState) -> None` method on both store implementations (or on RunStore ABC). This is called at the top of `put()` before any Redis interaction.

What to validate (per D-13: handoff targets, command state updates, transitions):
- If `status == RunStatus.WAITING_INTERRUPT`, then `pending_interrupt_id` must not be None
- If `status == RunStatus.WAITING_APPROVAL`, then `pending_approval` must not be None
- If `current_step` is not None, it must be a non-empty string
- Completed steps must be a list (no None values)

Exact validation rules are Claude's discretion, but must be meaningful enough that invalid state can never reach Redis.

### Pattern 7: v0.2.2 Fixture Test

```python
# tests/test_atomic_run_store.py (or a dedicated test_compat.py)
import json
from pathlib import Path
from governai.models.run_state import RunState

def test_v022_run_state_fixture_deserializes() -> None:
    fixture = Path("tests/fixtures/run_state_v022.json").read_text()
    state = RunState.model_validate_json(fixture)
    assert state.run_id is not None
    # No ValidationError means test passes
```

The fixture JSON is a real v0.2.2 RunState JSON blob committed to `tests/fixtures/run_state_v022.json`. The current RunState model has `model_config = {}` (empty, no extra="forbid"), so unknown fields are silently dropped — the fixture will deserialize without changes to RunState.

### Anti-Patterns to Avoid

- **Storing callables in AgentSpec:** Handler is not serializable. AgentSpec must never reference the handler function directly.
- **Calling `pipe.multi()` before `pipe.watch()`:** watch must come first. Commands between watch and multi are immediate-execute. Commands after multi are queued.
- **Catching bare `Exception` around the WATCH retry loop:** Only catch `WatchError` in the retry loop. Let `StateConcurrencyError` and other exceptions propagate immediately.
- **Computing schema fingerprint at `to_manifest()` time without registration:** If `tool.schema_fingerprint` is None (tool not registered), `to_manifest()` should either compute it inline or set it to None and document this. Do not silently emit an empty string.
- **Making `from_spec()` work without a registry:** D-05 is explicit — always raise if registry is None. No silent fallback.
- **Adding required fields to GovernedFlowSpec/GovernedStepSpec:** D-15 is explicit. Zero new required fields.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON Schema generation | Custom schema serializer | `model.model_json_schema()` | Pydantic v2 handles all edge cases: Optional fields, nested models, discriminated unions, $defs |
| Schema fingerprinting | Custom hash | `hashlib.blake2b(combined, digest_size=16).hexdigest()` | Phase 1 established this exact pattern; consistent with ToolRegistry |
| Atomic Redis writes | Manual WATCH logic | `client.pipeline(transaction=True)` as context manager | Pipeline handles connection management, UNWATCH on exit, WatchError signaling |
| Pydantic model round-trip | Custom JSON encoder | `model_dump_json()` / `model_validate_json()` | Pydantic v2 handles datetimes, enums, nested models, optional fields natively |
| Protocol type checking | Abstract base class | `typing.Protocol` with `@runtime_checkable` | Matches existing `ThreadAwareRunStore` pattern; structural subtyping |

**Key insight:** Every serialization concern is already solved by Pydantic v2. The only genuinely new engineering in this phase is the WATCH/MULTI/EXEC pipeline refactor and the FakeRedis extension for tests.

---

## Common Pitfalls

### Pitfall 1: FakeRedis Does Not Support Pipeline/Watch

**What goes wrong:** The existing `FakeRedis` in `tests/test_run_store.py` and `tests/test_interrupt_persistence.py` has no `pipeline()` method, no `watch()`, no `multi()`, no `execute()`. Tests that exercise the new atomic write path will fail with `AttributeError`.

**Why it happens:** FakeRedis was written to match only the operations used by the old non-atomic store.

**How to avoid:** Extend FakeRedis (or create a new `TransactionalFakeRedis`) with:
- `pipeline(transaction=True) -> FakePipeline` — returns a context manager
- `FakePipeline.watch(*keys)` — records watched keys
- `FakePipeline.multi()` — switches to queue mode
- `FakePipeline.set(key, value, ex=None)` — queues the operation
- `FakePipeline.rpush(key, value)` — queues the operation
- `FakePipeline.execute()` — runs queued operations; raises `WatchError` if any watched key was modified between watch and execute
- `FakePipeline.__aenter__` / `__aexit__` for context manager support

**Warning signs:** Tests that import `FakeRedis` and call `put()` on the new store immediately fail with `AttributeError: 'FakeRedis' object has no attribute 'pipeline'`.

### Pitfall 2: epoch Field Is Not Auto-Incremented

**What goes wrong:** RunState.epoch defaults to 0. If the runtime never increments epoch, every call to `put()` will see `state.epoch == 0` and `existing.epoch == 0` after the first write, triggering StateConcurrencyError on every subsequent write to the same run.

**Why it happens:** Epoch-based CAS only works if the caller increments epoch before each write.

**How to avoid:** Two options: (1) the store auto-increments epoch before the CAS check (`state.epoch = (existing.epoch or 0) + 1` inside `put()`), or (2) the runtime contract requires callers to increment epoch. Option 1 is simpler and eliminates a caller footgun. Option 2 is correct for true optimistic locking (caller must detect their own staleness). Since D-14 says "epoch-based compare-and-swap", option 2 is the intended semantics — but the workflow runtime must be updated to increment epoch.

**Warning signs:** All run store CAS tests pass in isolation but integration tests fail with StateConcurrencyError on every second write.

### Pitfall 3: schema_fingerprint Is None When Tool Not Registered

**What goes wrong:** `Tool.to_manifest()` is called on a Tool that was never registered with ToolRegistry. `tool.schema_fingerprint` is None (set in `__init__` as `self.schema_fingerprint: str | None = None`). The manifest has `schema_fingerprint=None`.

**Why it happens:** ToolRegistry.register() is the only place fingerprint is computed (Phase 1 design).

**How to avoid:** `to_manifest()` should compute fingerprint inline if `self.schema_fingerprint is None`. This makes the manifest always carry a fingerprint regardless of registration state.

**Warning signs:** `manifest.schema_fingerprint is None` in tests that create Tool directly without going through ToolRegistry.

### Pitfall 4: GovernedStepSpec Is a dataclass, Not a Pydantic Model

**What goes wrong:** Someone tries to add a field to GovernedStepSpec as a Pydantic field — but GovernedStepSpec is a plain Python `@dataclass`. It does not use `pydantic.BaseModel`.

**Why it happens:** app/spec.py uses standard `@dataclass` and `@dataclass(frozen=True)` throughout.

**How to avoid:** D-15 says no new fields anyway. But if validation of GovernedStepSpec fields is needed, it must use `__post_init__` not Pydantic validators.

**Warning signs:** `ValidationError` import in spec.py without a corresponding `BaseModel` subclass.

### Pitfall 5: Model Config Silent Extra Field Drop Is Not Verified

**What goes wrong:** The v0.2.2 fixture test assumes RunState silently drops unknown fields — but if someone adds `model_config = ConfigDict(extra="forbid")` to RunState in this phase, the fixture test breaks.

**Why it happens:** CONTEXT.md leaves unknown field handling as Claude's discretion, but changing it to `forbid` would break the backward compatibility requirement (D-16).

**How to avoid:** Keep `model_config` empty (or explicitly `extra="ignore"`) on RunState. The current empty config already silently ignores extra fields — verified by test. Do not add `extra="forbid"`.

**Warning signs:** `model_validate_json(fixture)` raises `ValidationError: Extra inputs are not permitted`.

### Pitfall 6: TTL Handling Inside WATCH/MULTI/EXEC

**What goes wrong:** The current store uses `client.set(key, payload, ex=int(self.ttl_seconds))` when TTL is set. Inside a MULTI/EXEC pipeline, `pipe.set(key, value, ex=...)` works correctly — but secondary expire calls (`client.expire(key, ttl)`) made outside the pipeline on the same key are not atomic with the write.

**Why it happens:** The current `_maybe_expire()` method is a separate async call. Inside the transaction, TTL should be set inline with `set(..., ex=ttl)` rather than as a follow-up `expire()`.

**How to avoid:** Inside the MULTI block, use `pipe.set(key, value, ex=int(self.ttl_seconds))` for both the run key and checkpoint key. The checkpoint index rpush TTL can be set after `execute()` (the index is not in the WATCH set, so a post-execute `expire()` is acceptable).

---

## Code Examples

### Round-Trip Verification Pattern

```python
# Source: verified against Pydantic v2 installed in .venv
from pydantic import BaseModel
from governai.agents.spec import AgentSpec

# Serialize
json_str = spec.model_dump_json()

# Deserialize
spec2 = AgentSpec.model_validate_json(json_str)

# Round-trip equality
assert spec.model_dump() == spec2.model_dump()
```

### WatchError-Based Retry Pattern

```python
# Source: redis.asyncio Pipeline source + redis.exceptions.WatchError
import asyncio
from redis.exceptions import WatchError

retries = 3
for attempt in range(retries + 1):
    async with client.pipeline(transaction=True) as pipe:
        try:
            await pipe.watch(run_key)
            # read current state for epoch check here (immediate mode)
            pipe.multi()
            pipe.set(run_key, payload)
            pipe.rpush(index_key, checkpoint_id)
            await pipe.execute()
            break
        except WatchError:
            if attempt >= retries:
                raise StateConcurrencyError(...) from None
            await asyncio.sleep(0.05 * (2 ** attempt))
```

### ModelSchemaRef Pattern

```python
# Source: Pydantic v2 model_json_schema() — verified working
from pydantic import BaseModel

class MyInput(BaseModel):
    question: str
    context: str = ""

schema = MyInput.model_json_schema()
# Returns: {"properties": {"question": {...}, "context": {...}}, "required": ["question"], ...}

ref = ModelSchemaRef(name=MyInput.__name__, schema=schema)
# ref.name = "MyInput"
# ref.schema = {"properties": ..., "type": "object", ...}
```

### FakeRedis Pipeline Extension Pattern

```python
# Pattern for test FakeRedis — must support WATCH/MULTI/EXEC
class FakePipeline:
    def __init__(self, store: "FakeRedis") -> None:
        self._store = store
        self._watched: set[str] = set()
        self._queued: list[tuple] = []
        self._multi_active = False
        self._original_values: dict[str, str | None] = {}

    async def __aenter__(self) -> "FakePipeline":
        return self

    async def __aexit__(self, *args) -> None:
        pass  # no-op reset for fake

    async def watch(self, *keys: str) -> None:
        for key in keys:
            self._watched.add(key)
            self._original_values[key] = self._store.data.get(key)

    def multi(self) -> None:
        self._multi_active = True

    def set(self, key: str, value: str, ex=None) -> None:
        if self._multi_active:
            self._queued.append(("set", key, value))

    def rpush(self, key: str, value: str) -> None:
        if self._multi_active:
            self._queued.append(("rpush", key, value))

    async def execute(self) -> list:
        from redis.exceptions import WatchError
        for key in self._watched:
            if self._store.data.get(key) != self._original_values.get(key):
                raise WatchError(f"Key {key} changed")
        results = []
        for op in self._queued:
            if op[0] == "set":
                self._store.data[op[1]] = op[2]
                results.append(True)
            elif op[0] == "rpush":
                self._store.lists.setdefault(op[1], []).append(op[2])
                results.append(len(self._store.lists[op[1]]))
        return results
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Two-step write (checkpoint then state) | WATCH/MULTI/EXEC atomic write | Phase 2 | Crash between the two writes no longer corrupts run state |
| Agent fields accessible only via live Agent instance | AgentSpec serializable descriptor | Phase 2 | Studio can store/transmit agent metadata without Python imports |
| Tool metadata only via live Tool instance | ToolManifest read-only descriptor | Phase 2 | Policy engine and Studio can evaluate tool capabilities without callable |

**Deprecated/outdated:**
- None within this phase — all changes are additions or refactors of existing methods.

---

## Open Questions

1. **Should `RunStore.put()` (ABC) declare atomic write semantics in its docstring?**
   - What we know: The ABC currently says "Persist a run state snapshot." with no atomicity guarantee.
   - What's unclear: Whether InMemoryRunStore callers expect the new CAS behavior to raise errors.
   - Recommendation: Update the ABC docstring to say "Atomically persist a run state snapshot. Raises StateConcurrencyError if optimistic lock conflict cannot be resolved." This is a documentation-only change that costs nothing.

2. **Should epoch be auto-incremented inside `put()` or is it a caller contract?**
   - What we know: RunState.epoch exists and defaults to 0. CONTEXT.md does not specify.
   - What's unclear: Whether the workflow runtime currently increments epoch at all — it does not appear to do so in the current code.
   - Recommendation: Auto-increment epoch inside `put()` (`state.epoch = (existing.epoch or 0) + 1` before writing) to avoid a breaking change for existing callers. This is the simpler path and preserves the CAS guarantee. Log the decision in PROJECT.md.

3. **Should `StateConcurrencyError` be exported from the top-level `__init__.py`?**
   - What we know: Other store-layer errors (`RunStore`, `InMemoryRunStore`, `RedisRunStore`) are exported. Consumer code that calls `put()` will need to handle `StateConcurrencyError`.
   - What's unclear: Whether Zeroth catches store errors by type or by catching broadly.
   - Recommendation: Export it. The pattern is consistent with other exported types.

4. **Exact PERS-03 validation rules for transitions and handoff targets**
   - What we know: D-13 says "handoff targets, command state updates, and transitions." The RunState model has no explicit transition or handoff fields — these would be in the `channels` or `artifacts` dicts, or validated against the flow spec.
   - What's unclear: Without a GovernedFlow reference, the store cannot validate handoff targets against the spec. This seems like it requires a flow spec reference in the store, which contradicts the store's current design as a dumb persistence layer.
   - Recommendation: Limit PERS-03 to structural validation (epoch consistency, required status-field relationships) rather than semantic validation against a flow spec. Flag for planner to confirm scope.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|---------|
| Python 3.12 | Project minimum | ✓ | 3.12.12 (.venv) | — |
| pydantic | AgentSpec, ToolManifest | ✓ | 2.12.5 | — |
| redis.asyncio | RedisRunStore atomic writes | ✓ | 7.3.0 | — |
| pytest | Test suite | ✓ | 9.0.2 (.venv) | — |
| hashlib | Schema fingerprinting | ✓ | stdlib | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None — all required dependencies are present.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` `testpaths = ["tests"]` |
| Quick run command | `.venv/bin/pytest tests/test_agent_spec.py tests/test_tool_manifest.py tests/test_atomic_run_store.py -x` |
| Full suite command | `.venv/bin/pytest tests/ -q` (115 tests currently, ~0.54s) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SPEC-01 | AgentSpec is a Pydantic BaseModel with all non-callable Agent fields | unit | `.venv/bin/pytest tests/test_agent_spec.py::test_agent_spec_fields -x` | ❌ Wave 0 |
| SPEC-02 | Agent.from_spec() round-trips to a runtime Agent with identical config | unit | `.venv/bin/pytest tests/test_agent_spec.py::test_agent_from_spec_round_trip -x` | ❌ Wave 0 |
| SPEC-03 | AgentSpec round-trips through model_dump_json() / model_validate_json() | unit | `.venv/bin/pytest tests/test_agent_spec.py::test_agent_spec_json_round_trip -x` | ❌ Wave 0 |
| MFST-01 | ToolManifest is a Pydantic BaseModel with all Tool data fields | unit | `.venv/bin/pytest tests/test_tool_manifest.py::test_tool_manifest_fields -x` | ❌ Wave 0 |
| MFST-02 | Tool.to_manifest() extracts a ToolManifest from a live Tool | unit | `.venv/bin/pytest tests/test_tool_manifest.py::test_tool_to_manifest -x` | ❌ Wave 0 |
| MFST-03 | ToolManifest carries schemas, capabilities, placement, version | unit | `.venv/bin/pytest tests/test_tool_manifest.py::test_manifest_carries_all_fields -x` | ❌ Wave 0 |
| PERS-01 | Crash between write and cache leaves last committed state intact | unit | `.venv/bin/pytest tests/test_atomic_run_store.py::test_atomic_write_crash_safety -x` | ❌ Wave 0 |
| PERS-02 | RedisRunStore uses WATCH/MULTI/EXEC; WatchError triggers retry | unit | `.venv/bin/pytest tests/test_atomic_run_store.py::test_redis_optimistic_lock_conflict -x` | ❌ Wave 0 |
| PERS-03 | RunStore.put() validates state before writing | unit | `.venv/bin/pytest tests/test_atomic_run_store.py::test_store_validates_before_write -x` | ❌ Wave 0 |
| D-16 | v0.2.2 RunState JSON fixture deserializes without ValidationError | unit | `.venv/bin/pytest tests/test_atomic_run_store.py::test_v022_fixture_deserializes -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `.venv/bin/pytest tests/test_agent_spec.py tests/test_tool_manifest.py tests/test_atomic_run_store.py -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_agent_spec.py` — covers SPEC-01, SPEC-02, SPEC-03
- [ ] `tests/test_tool_manifest.py` — covers MFST-01, MFST-02, MFST-03
- [ ] `tests/test_atomic_run_store.py` — covers PERS-01, PERS-02, PERS-03, D-16
- [ ] `tests/fixtures/run_state_v022.json` — the committed v0.2.2 RunState JSON blob
- [ ] `governai/agents/spec.py` — AgentSpec, ModelSchemaRef, ModelRegistry protocol
- [ ] `governai/tools/manifest.py` — ToolManifest

---

## Sources

### Primary (HIGH confidence)

- Pydantic v2 installed in .venv (2.12.5) — verified `model_json_schema()`, `model_dump_json()`, `model_validate_json()`, `model_config` behavior
- redis.asyncio installed in .venv (7.3.0) — inspected Pipeline source: `watch()`, `multi()`, `execute()`, `WatchError` propagation, `pipeline(transaction=True)` context manager
- `governai/agents/base.py` — Agent.__init__ parameter list (source of truth for AgentSpec fields)
- `governai/tools/base.py` — Tool.__init__ parameter list (source of truth for ToolManifest fields)
- `governai/runtime/run_store.py` — current RedisRunStore.put() and write_checkpoint() (refactor target)
- `governai/models/run_state.py` — RunState model_config (empty → silently drops unknown fields)
- `governai/tools/registry.py` — blake2b fingerprint pattern (Phase 1 source to replicate)

### Secondary (MEDIUM confidence)

- Full test suite run confirming 115 tests pass in 0.54s — establishes baseline for regression protection
- RunState serialization output verified via `.venv/bin/python` — epoch field present, unknown fields silently dropped

### Tertiary (LOW confidence)

- None — all claims verified against installed source code.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified installed versions, source inspected
- Architecture: HIGH — code patterns read directly from source; no assumptions
- Pitfalls: HIGH — identified from direct source inspection (FakeRedis, epoch, fingerprint=None)

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (pydantic and redis.asyncio are stable; patterns are from installed source)
