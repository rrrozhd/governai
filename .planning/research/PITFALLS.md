# Pitfalls Research

**Domain:** Adding governance depth features to an existing async Python workflow framework with a downstream consumer (Zeroth)
**Researched:** 2026-04-05
**Confidence:** HIGH (code inspected directly; external sources verified core async/Redis/Pydantic patterns)

---

## Critical Pitfalls

### Pitfall 1: Breaking Zeroth's RunState Subclass with Model Field Additions

**What goes wrong:**
Zeroth's `Run` model extends `RunState`. Any new required field added to `RunState` (e.g., `thread_lifecycle_state`, `secrets_context`) without a default value will cause `ValidationError` when Zeroth constructs its `Run` subclass without supplying the new field. Even optional fields with `Field(default=...)` are safe, but new `model_validator(mode="after")` validators that mutate existing fields can silently break Zeroth's deserialization path if the validator uses new fields that Zeroth's serialized Redis data does not carry.

**Why it happens:**
`RunState` is a Pydantic `BaseModel`. Subclasses inherit all validators. When Zeroth reads a `Run` from Redis via `RunState.model_validate_json()`, then Zeroth's `Run.model_validate_json()` calls the parent validators. A validator added to `RunState` that touches a new field will fail on old serialized payloads missing that field — especially if the new field has no default.

The existing `_default_thread_id` validator on `RunState` is a template for this pattern. Adding a second validator that, say, ensures `lifecycle_state` is `ThreadLifecycleState.ACTIVE` when `status` is `RUNNING` will silently fail on Zeroth's old in-flight runs until they expire.

**How to avoid:**
- All new fields on `RunState` must have explicit `default` or `default_factory` values. Never add required fields.
- New `model_validator` entries must be purely additive — they set defaults but never raise on missing new fields.
- Add a `model_config = ConfigDict(extra="ignore")` review: the current model uses Pydantic v2 defaults, which ignores extra fields. Verify this is still true after each new field.
- Maintain a migration note: old Redis payloads round-tripped through `model_validate_json` must produce a valid `RunState`.

**Warning signs:**
- `ValidationError` on `model_validate_json` in Zeroth after GovernAI upgrade.
- `KeyError` or `AttributeError` inside a new `model_validator` when loading old checkpoints.
- Zeroth's test suite passes but production runs loaded from Redis fail on resume.

**Phase to address:** Phase that introduces `RunState` changes (rich thread lifecycle, secrets context). Must include a cross-version deserialization test that validates old serialized `RunState` payloads round-trip cleanly through the new model.

---

### Pitfall 2: Async Deadlock When Adding asyncio.Lock to the Runtime Loop

**What goes wrong:**
Adding an `asyncio.Lock` inside `LocalRuntime._persist_state` (or wrapping `RedisRunStore.put`) to implement transactional write-ahead will deadlock if the lock is acquired by a coroutine that then calls `await self._persist_state(state)` recursively — which already happens in `run_workflow` (called once for PENDING, once for RUNNING) and in `_advance`. Any lock that is not re-entrant will dead-lock on the second `await self._persist_state()` call within the same task.

`asyncio.Lock` is not re-entrant in Python. A task that owns the lock and awaits another coroutine that tries to acquire the same lock will hang indefinitely. This is not a theoretical edge case — `run_workflow` already calls `_persist_state` twice before entering `_advance`, which calls `_persist_state` again on every step transition.

**Why it happens:**
Developers assume asyncio locks behave like database transactions and wrap all persistence calls. But within a single task's call chain, the lock is already held when the next `_persist_state` call is made.

**How to avoid:**
- Use a per-run-id lock (a `dict[str, asyncio.Lock]` keyed by `run_id`), not a single instance-wide lock. Each run is already single-consumer, so per-run locking is both safe and deadlock-free within one event loop.
- Keep the lock strictly at the cross-process / cross-replica boundary (i.e., a Redis distributed lock), not inside the in-process async call chain. The in-process path is already sequential per run.
- If wrapping `RedisRunStore.put` with a Redis lock: acquire the lock once at the `run_workflow`/`resume_workflow` entry point, not at every `_persist_state` call.
- The `RedisInterruptStore` uses a synchronous `redis.Redis` client (not `redis.asyncio`). Wrapping its calls in `asyncio.to_thread` or `loop.run_in_executor` before acquiring any `asyncio.Lock` prevents the event loop from blocking.

**Warning signs:**
- Test hangs indefinitely with `asyncio.wait_for` timeout.
- `run_workflow` completes the PENDING persist but never emits `RUN_STARTED`.
- Redis distributed lock: `redis.asyncio.Lock.release()` cancelled mid-operation leaves the key permanently held (confirmed redis-py bug #3847).

**Phase to address:** Phase implementing transactional state persistence. Architecture decision must be made upfront: per-run lock at the entry boundary, not inside the persistence helper.

---

### Pitfall 3: Policy Fault Isolation Using asyncio.wait_for Swallowing CancelledError

**What goes wrong:**
Adding per-policy timeouts with `asyncio.wait_for(run_policy(func, ctx), timeout=policy_timeout)` will silently fail if a policy coroutine internally suppresses `CancelledError` (e.g., wraps `await some_llm_call()` in `try/except Exception`). Python's `asyncio.wait_for` cancels the task on timeout by sending `CancelledError`. If the coroutine catches `Exception` broadly, the cancellation is swallowed, the policy runs beyond its timeout, and the surrounding `wait_for` either hangs or raises unexpectedly.

In Python 3.12 specifically, there is a documented bug where `CancelledError` propagates unexpectedly to an outer scope when exceptions are raised inside nested `TaskGroup` or `timeout` blocks. GovernAI targets Python 3.12+.

**Why it happens:**
Policy authors commonly write `try/except Exception: pass` or `try/except Exception as e: return PolicyDecision(allow=False, reason=str(e))` to make policies non-throwing. This broad catch intercepts `asyncio.CancelledError` (which subclasses `BaseException` in Python 3.8+ but was `Exception` in 3.7) — actually `CancelledError` is a `BaseException` in 3.8+, so broad `except Exception` does *not* catch it. However, `except BaseException` or bare `except` will. Policies copied from synchronous patterns may use bare `except`.

The deeper issue is that on timeout, the partially-run policy's side effects (external HTTP calls, LLM calls) are not rolled back. The policy appears to have failed cleanly when it actually timed out mid-flight.

**How to avoid:**
- Wrap each policy call in `asyncio.wait_for` at the `PolicyEngine.evaluate` call site, not inside individual policies.
- Catch `asyncio.TimeoutError` explicitly after `wait_for`, not `Exception`.
- Mark timed-out policies as `PolicyDecision(allow=False, reason="policy_timeout")` and emit a `POLICY_DENIED` audit event with metadata `{"timeout": True}`.
- Document in policy authoring guide: policies must not catch `BaseException` or use bare `except`.
- Test with a policy that sleeps longer than the timeout to verify the timeout fires and the engine continues.

**Warning signs:**
- A policy that calls an external service hangs `PolicyEngine.evaluate` indefinitely.
- `PolicyDeniedError` raised from the wrong policy name (timeout in one policy misattributed).
- Audit log shows `POLICY_CHECKED` with no corresponding `POLICY_DENIED` before the engine raises.

**Phase to address:** Phase implementing policy fault isolation and capability model.

---

### Pitfall 4: RunState model_copy(deep=True) Performance with Large Artifact Payloads

**What goes wrong:**
Every `RunStore.put` call — both `InMemoryRunStore` and `RedisRunStore.write_checkpoint` — calls `state.model_copy(deep=True)`. At step granularity, this is called on every step transition. If `RunState.artifacts` contains large byte payloads (e.g., agent tool outputs, memory connector results), `model_copy(deep=True)` will deepcopy the entire artifact dict on every step.

Benchmarks show `deepcopy` is 664x slower than shallow copy for large nested dicts, and can consume 25% of runtime for game-state-sized objects (~1000 items). In a 10-step workflow where each step appends a 100KB blob to `artifacts`, the total deepcopy cost across all checkpoints is O(steps * artifact_size).

Adding new feature data to `RunState` (memory connector results, secrets context references, lifecycle metadata) amplifies this cost.

**Why it happens:**
`model_copy(deep=True)` is the safe default for snapshot isolation. Developers adding new model fields don't consider that adding a `memory_results: dict[str, Any]` field to `RunState` that stores raw LLM outputs or retrieved memory chunks will be deepcopied on every step.

**How to avoid:**
- Large blobs belong in a content-addressed artifact store (e.g., Redis key by hash), not in `RunState.artifacts` directly. `RunState` should store artifact IDs, not artifact content.
- New fields for memory connector results, secrets context, etc., must not hold raw payloads — hold references/IDs only.
- The `InMemoryRunStore` test variant can use shallow copy for test performance; only production paths need deep copy.
- Add a size guard: emit a warning audit event if `len(state.model_dump_json()) > threshold_bytes` on persist.

**Warning signs:**
- Step latency increases linearly with workflow step count.
- Memory usage grows unexpectedly during multi-step runs.
- `cProfile` shows `copy.deepcopy` in the top 3 hotspots.

**Phase to address:** Any phase that adds new fields to `RunState`. Establish the "no raw payloads in RunState" rule before transactional persistence and memory connector phases.

---

### Pitfall 5: Redis Key Space Pollution from New Feature Prefixes

**What goes wrong:**
The existing `RedisRunStore` uses prefix `governai:run`, `RedisInterruptStore` uses `governai:interrupt`, and `RedisAuditEmitter` uses its own prefix. New features — interrupt TTL cleanup, thread lifecycle indexes, memory connector backends, audit enrichment storage — will introduce new key patterns. Without a coordinated namespace plan, keys will either collide (two features write to `governai:run:thread:{id}:active` with different semantics) or accumulate without TTL (memory connector cache keys with no expiry).

Specifically: the new interrupt TTL cleanup sweeper, if it scans by pattern, will match interrupt index keys and checkpoint index keys if prefixes are inconsistent. The existing `RedisRunStore._thread_checkpoint_index_key` and `_thread_run_index_key` use the `governai:run` prefix for thread-scoped lists, while `RedisInterruptStore` uses `governai:interrupt:run:{run_id}:requests` — a different namespace shape. New thread lifecycle keys need a third namespace shape decided upfront.

**Why it happens:**
Features are added incrementally without a Redis key schema document. Each developer chooses a key pattern locally that seems non-colliding, but cross-feature scans (e.g., "all keys for thread X") fail because patterns don't match.

**How to avoid:**
- Define and document the full Redis key schema before implementing any new feature's persistence:
  ```
  governai:run:{run_id}                        # RunState snapshot
  governai:run:checkpoint:{checkpoint_id}      # Checkpoint snapshot
  governai:run:thread:{thread_id}:runs         # Run index list
  governai:run:thread:{thread_id}:checkpoints  # Checkpoint index list
  governai:run:thread:{thread_id}:active       # Active run pointer
  governai:interrupt:run:{run_id}:...          # Interrupt data
  governai:thread:{thread_id}:lifecycle        # New: thread lifecycle record
  governai:memory:{scope_id}:...               # New: memory connector
  ```
- All new keys must carry TTL if their lifecycle is bounded (interrupt TTL, memory session TTL).
- Add a `prefix` constructor argument to all new Redis-backed stores, consistent with existing `RedisRunStore(prefix="governai:run")` pattern.

**Warning signs:**
- KEYS scan returns unexpected count when enumerating "all run keys".
- Thread lifecycle delete removes an interrupt index list instead of the lifecycle record.
- Memory connector entries accumulate in Redis with no expiry.

**Phase to address:** Before any new Redis-backed store is implemented. Define the schema table once in the architecture docs and enforce it across all feature phases.

---

### Pitfall 6: Secrets Leaking into Audit Events via payload dict

**What goes wrong:**
`AuditEvent.payload` is `dict[str, Any]`. The runtime emits audit events at every policy check, step entry, tool execution, and agent call. Adding a "secrets-aware execution context" that injects resolved secrets into the `ExecutionContext` is safe in isolation. The leak vector is the policy context: `PolicyContext` is passed to policies, and policies sometimes emit their own audit payloads (via `PolicyDecision.reason` or future enrichment metadata). If policy authors include `ctx.secrets["OPENAI_API_KEY"]` in an audit reason string — even accidentally — it flows directly into `RedisAuditEmitter` and is durably persisted.

A second vector: `RunState.artifacts` holds step outputs. If a step returns a dict that happens to reference a secret (e.g., a tool result that echoes back environment info), it's deepcopied into the artifact store and persisted.

**Why it happens:**
The framework's open `dict[str, Any]` audit payload allows any data. Secret values are strings, indistinguishable from non-secret strings at the persistence layer. The redaction requirement is "automatic" per the feature spec, meaning no policy author should need to think about it.

**How to avoid:**
- Secrets must be represented in the runtime as opaque references (a `SecretRef(name="X")` wrapper), never as resolved string values inside any model field.
- Resolved values are injected into the execution context at the last responsible moment — inside the tool/step execution call — not stored in `PolicyContext` or `RunState`.
- The audit emitter must run a redaction pass: scan `payload` recursively for any string value that matches a registered secret name pattern and replace with `"[REDACTED]"` before persisting.
- `AuditEmitter.emit` is the correct redaction point — it fires on every event regardless of emitter type.
- Test: emit an audit event with a known secret value in the payload; assert the persisted payload contains `"[REDACTED]"`.

**Warning signs:**
- Audit log contains strings matching environment variable values.
- `RedisAuditEmitter` stores events with `policy_reason` fields containing API key substrings.
- `PolicyContext.metadata` grows to include resolved secret values.

**Phase to address:** Secrets-aware execution context phase. Redaction must be built into `AuditEmitter` before secrets are resolved anywhere in the runtime.

---

### Pitfall 7: AuditEvent Fixed Schema Blocking Enrichment Without Backward Compatibility

**What goes wrong:**
`AuditEvent` has a fixed schema with `payload: dict[str, Any]` as the extension point. The "audit event enrichment protocol" feature adds typed extension metadata. If this is implemented by adding new typed fields directly to `AuditEvent` (e.g., `policy_metadata: PolicyAuditMeta | None`), every existing consumer of `AuditEvent` — including Zeroth's `audit/` module — must be updated simultaneously. If Zeroth deserializes events from Redis and the new fields are absent in old events, `model_validate_json` will fail if the fields lack defaults.

A second failure mode: enrichment metadata passed as `payload` sub-keys (e.g., `payload["_meta"]`) bypasses Pydantic validation entirely and cannot be type-checked.

**Why it happens:**
The `payload: dict[str, Any]` field is intentionally open, making it tempting to just stuff enrichment data there. But this creates an untyped blob that Zeroth's audit consumers cannot safely iterate.

**How to avoid:**
- Use a typed `extensions: list[AuditEventExtension]` field on `AuditEvent` with `default_factory=list`. All existing events deserialize with an empty list.
- `AuditEventExtension` is a discriminated union keyed on `extension_type: str`, so new extension types are additive.
- Old events serialized without `extensions` deserialize to `extensions=[]` — fully backward compatible.
- Zeroth's enriched audit models should migrate to emit `AuditEventExtension` instances rather than custom payload keys.

**Warning signs:**
- `model_validate_json` raises `ValidationError` when reading old audit events after schema change.
- Zeroth audit consumers receive `KeyError` accessing `payload["_meta"]` on older events.
- Extension data appears in both `payload` dict and new typed field (double-write inconsistency).

**Phase to address:** Audit event enrichment protocol phase. The extension field must be added with `default_factory=list` before any enrichment data is emitted.

---

### Pitfall 8: Interrupt TTL Enforcement Racing with the Resume Path

**What goes wrong:**
`InterruptManager.get_pending` already checks expiry. But the race is between the expiry check and the resume: a client reads `get_pending_interrupt` (TTL valid, returns request), then the TTL expires before `resume_workflow` calls `_interrupt_resolve`. The `resolve` method re-checks `expires_at` and raises `ValueError("Interrupt ... has expired")`. This is an unhandled exception from the caller's perspective — `resume_workflow` propagates it as an unexpected error, not as a typed `InterruptExpiredError`.

Adding active TTL enforcement (a sweeper that deletes expired requests) makes this race worse: the sweeper may delete the request between `get_pending` and `resolve`, causing `_interrupt_resolve` to raise `KeyError("Unknown interrupt_id")` instead of a meaningful TTL error.

**Why it happens:**
TTL enforcement is added as a cleanup job that runs independently of the resume path, without coordinating with the `InterruptManager.resolve` method's own expiry check.

**How to avoid:**
- Add `InterruptExpiredError` as a typed exception in `governai.workflows.exceptions`.
- `InterruptManager.resolve` should raise `InterruptExpiredError` (not `ValueError`) on TTL expiry — distinguishable from epoch mismatch.
- `resume_workflow` must catch `InterruptExpiredError` specifically, transition the run to `FAILED` with `error="interrupt_expired"`, emit `INTERRUPT_EXPIRED` audit event, and re-raise `InterruptExpiredError` to the caller.
- The sweeper must not delete expired requests immediately — mark as `status="expired"` and let `resolve` raise the typed error. Actual deletion is deferred to `clear_expired` called post-resume.
- The existing `INTERRUPT_EXPIRED` event type in `EventType` already exists — wire it up from the `resume_workflow` path.

**Warning signs:**
- `resume_workflow` raises `ValueError` or `KeyError` instead of a typed error when the interrupt has expired.
- Zeroth's run management layer catches `KeyError` from a resume attempt and incorrectly marks the run as "not found".
- Audit log has no `INTERRUPT_EXPIRED` event before the `RUN_FAILED` event when an interrupt times out.

**Phase to address:** Interrupt TTL enforcement phase. Must ship `InterruptExpiredError`, the audit event wire-up, and the typed catch in `resume_workflow` as a single unit.

---

### Pitfall 9: AgentSpec and ToolManifest Serialization Breaking Existing Tool/Agent Construction

**What goes wrong:**
Adding `AgentSpec` (serializable agent definition) and `ToolManifest` (serializable tool definition) requires extracting currently-imperative construction patterns into declarative models. Zeroth currently builds agents via `GovernedFlowSpec`/`GovernedStepSpec` imperative Python. If `AgentSpec` is added as a required field on `GovernedStepSpec` (or as a mandatory constructor argument on `Agent`), every existing Zeroth flow definition breaks.

A secondary issue: `ToolManifest` serialized to JSON must round-trip. `Tool` currently holds callable references (Python functions). If `ToolManifest` tries to serialize the callable, it fails. If it serializes only metadata (name, schema, placement), the manifest cannot reconstruct the tool without a registry lookup — and that registry lookup path must be defined.

**Why it happens:**
The temptation is to replace the existing `Tool` and `Agent` classes with their spec equivalents. The correct relationship is `AgentSpec` as a separate serializable descriptor that can *produce* an `Agent` when combined with a registry, not replace it.

**How to avoid:**
- `AgentSpec` and `ToolManifest` are additive: new standalone models that do not modify existing `Agent`, `Tool`, `GovernedStepSpec`, or `GovernedFlowSpec` constructors.
- Existing construction paths remain unchanged. `AgentSpec.to_agent(registry)` is a factory method that produces an `Agent` from the spec and a tool/skill registry.
- `GovernedStepSpec` gets an optional `agent_spec: AgentSpec | None = None` field; it does not replace `agent`.
- `ToolManifest` serializes only the tool contract (name, input schema, output schema, version, placement) — not the callable. Registry lookup is the tool's responsibility.

**Warning signs:**
- Zeroth's `GovernedFlowSpec` construction raises `ValidationError` after GovernAI upgrade.
- Existing tool test suite fails because `Tool.__init__` signature changed.
- `AgentSpec.model_dump_json()` raises `PydanticSerializationError` on callable fields.

**Phase to address:** AgentSpec and ToolManifest phase. Integration test: Zeroth's existing flow construction must pass unchanged after the phase.

---

### Pitfall 10: Memory Connector Protocol Adding Blocking I/O on the Async Event Loop

**What goes wrong:**
A "pluggable memory backend" means third-party implementations. Implementors commonly write synchronous backends (database ORM calls, file I/O, vector store SDKs without async support). If the memory connector protocol defines `async def query(...)` but the runtime calls it without guarding against synchronous implementations, a synchronous implementation that does `time.sleep` or `requests.get` inside an `async def` will block the entire event loop.

The existing `RedisInterruptStore` already has this issue: it uses a synchronous `redis.Redis` client. The `InterruptManager.uses_blocking_io()` flag signals this, and the runtime wraps calls in `asyncio.to_thread`. The memory connector protocol must define a similar mechanism.

**Why it happens:**
Protocol implementors treat `async def` as syntactic decoration, not a contract. Without an explicit test harness that verifies the implementation does not block the event loop (e.g., using `asyncio-mode strict` in pytest), blocking implementations pass all tests in CI.

**How to avoid:**
- The memory connector protocol must document the blocking I/O contract explicitly.
- Provide a `SyncMemoryBackend` base class with a `blocking_io = True` flag, mirroring `InterruptStore.blocking_io`.
- The runtime wraps `blocking_io = True` memory calls in `asyncio.to_thread` automatically.
- Include a test fixture that injects a slow-sleeping sync backend and asserts the event loop does not stall (use `pytest-asyncio` with `asyncio.get_event_loop().is_running()` check).

**Warning signs:**
- Adding a vector store memory backend causes all async tests to pass but production event loop latency spikes.
- `asyncio` debug mode (`PYTHONASYNCIODEBUG=1`) reports coroutines taking > 100ms in the event loop thread.
- Memory backend authors complain the `async def` interface is inconvenient for sync SDKs.

**Phase to address:** Memory connector protocol phase. Define and test the `blocking_io` contract before the first external backend is implemented.

---

### Pitfall 11: Contract Versioning Colliding with Zeroth's Existing Registry

**What goes wrong:**
Zeroth maintains its own `contracts/registry.py` for contract versioning today. GovernAI adding a first-class contract versioning primitive means Zeroth must migrate from its internal registry to GovernAI's. If both coexist during the transition, a tool can be registered in both registries with different version interpretations, causing version resolution to return different results depending on which registry is consulted.

The migration is blocked if GovernAI's versioning model makes assumptions Zeroth's model does not (e.g., GovernAI uses semver `ToolVersion(major=1, minor=0, patch=0)` while Zeroth uses opaque string versions like `"v2-alpha"`).

**Why it happens:**
GovernAI contract versioning is designed against an abstract notion of "versioning" without first reading Zeroth's existing `contracts/registry.py`. The two implementations diverge in schema, resolution semantics, or both.

**How to avoid:**
- Read Zeroth's `contracts/registry.py` before designing GovernAI's contract versioning model. The GovernAI primitive must be a superset of, or directly compatible with, Zeroth's existing format.
- GovernAI's `ContractVersion` must accept Zeroth's existing version strings without re-serialization.
- Design the migration so Zeroth can swap `contracts/registry.py` for `governai.ContractRegistry` in a single PR with no behavior change.
- Do not deprecate Zeroth's registry on the GovernAI side — GovernAI provides the primitive; Zeroth chooses when to migrate.

**Warning signs:**
- Zeroth's contract resolution returns a different tool version than GovernAI's registry for the same tool name.
- `tool.version` is a string in Zeroth but a structured object in GovernAI, causing `TypeError` on comparison.
- Zeroth's Studio phase is blocked because contract version is not serializable to the expected JSON shape.

**Phase to address:** Contract versioning phase. Must include a compatibility test using Zeroth's actual version string formats before the phase is marked complete.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Adding raw payloads to `RunState.artifacts` for memory results | Simple, no new model fields | deepcopy cost grows O(N) with payload size; breaks the "RunState is a control record, not a data store" invariant | Never — use artifact IDs |
| Stuffing enrichment metadata in `AuditEvent.payload` as untyped dict | No model changes needed | Zeroth audit consumers must use `.get()` everywhere; no type safety; schema diverges across codebases | Only for temporary debugging, never in production path |
| A single instance-wide `asyncio.Lock` for persistence | Simple to reason about | Deadlocks on re-entrant persist calls in `run_workflow` (which calls `_persist_state` twice before `_advance`) | Never — use per-run-id locks |
| Resolving secrets to plain strings in `PolicyContext.metadata` | Policies can check secret values | Secrets leak into audit events via `PolicyDecision.reason` | Never — use `SecretRef` wrappers |
| Sharing the `governai:run` Redis prefix for thread lifecycle keys | No new prefix to configure | Thread lifecycle list operations can accidentally match run checkpoint index keys in scan/delete operations | Never in production; tests only if keys are namespaced |
| Making `AgentSpec` a required field on `GovernedStepSpec` | Clean model — every step has a spec | Breaks all existing Zeroth flow definitions without a migration path | Never without a major version bump |
| Implementing memory connector `async def` without `blocking_io` guard | Protocol is simple | Synchronous backend implementations block the event loop silently | Never in the protocol contract |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Redis distributed lock (new) + existing `RedisRunStore.put` | Wrapping `put` with a Redis lock acquired inside every `_persist_state` call — causes lock acquisition on every step transition | Acquire the distributed lock once at `run_workflow`/`resume_workflow` entry; hold it for the run's active duration |
| `RedisInterruptStore` (sync client) + new async features | Calling `interrupt_store.save_request()` directly inside an `async def` without `asyncio.to_thread` | Use the existing `InterruptManager.uses_blocking_io()` flag pattern; wrap blocking calls in `asyncio.to_thread` |
| Zeroth's `Run.model_validate_json` + new `RunState` fields | Adding a field without a default causes `ValidationError` on old Redis-serialized runs | Every new `RunState` field must have `default` or `default_factory`; add a deserialization test using an old-format JSON fixture |
| `AuditEmitter.emit` + secrets context | Passing resolved secret values in `event.payload` | Redaction pass runs inside `emit` before persistence; secrets stored as `SecretRef` objects until execution point |
| Thread lifecycle state + existing `RunStatus` | Adding a parallel state machine in `RunState` that can conflict with `RunStatus` (e.g., `thread_state=ARCHIVED` but `status=RUNNING`) | Thread lifecycle state lives on a separate `Thread` model, not embedded in `RunState`; `RunState` only tracks run-level status |
| Memory connector + existing `ExecutionContext` | Injecting memory results directly into `RunState.channels` as a side-effect | Memory connector reads/writes via its own protocol; `ExecutionContext` holds a reference to the connector, not to resolved values |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `model_copy(deep=True)` on RunState with large artifacts | Step latency grows linearly with artifact size; memory usage spikes mid-workflow | Store artifact IDs in `RunState.artifacts`, not raw blobs | At ~50KB per artifact per step, noticeable at 5+ steps in a multi-turn workflow |
| `list_run_ids` in `RedisRunStore` performing N GET calls to validate each run ID | `list_thread_runs` latency grows O(N) with thread history length | Pipeline the GET calls using Redis MGET; or maintain a separate count key | Noticeable when a thread has > 20 historical runs |
| Policy engine evaluating all policies on every step, including expensive LLM-backed policies | Latency spike at policy check even for trivially-safe steps | Capability model: policies declare their `required_capabilities`; the engine skips policies whose capabilities are not required by the current step | When any one policy costs > 200ms and there are > 3 policies registered globally |
| Interrupt sweeper (`clear_expired`) scanning all interrupts for all runs | Sweeper call blocks event loop if `RedisInterruptStore` is used (sync client) | Sweeper must use `asyncio.to_thread` when `blocking_io=True`; scope sweeper to known run IDs, not a Redis SCAN | When there are > 1000 active interrupt records |
| Audit enrichment protocol adding per-event enrichment callbacks | All enrichers called synchronously inside `emit`; a slow enricher blocks audit persistence | Enrichers must be async and timeout-guarded; slow enrichers emit a WARN event rather than blocking | When any enricher performs I/O and audit volume is > 100 events/second |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Resolved secret values in `PolicyContext` | Policy `reason` strings captured in audit events contain secret values; durably persisted in Redis | `PolicyContext` receives `SecretRef` objects only; resolution happens inside the execution backend, not in the policy layer |
| Secret names leaked in audit payload | Enumerating secret names allows attackers to identify credential types in use | Redaction covers both values and optionally names; configurable per-deployment |
| Memory connector caching resolved memory with no TTL | Long-lived memory entries hold stale data and accumulate without bound | Memory connector protocol requires `ttl_seconds` on all cached entries; default TTL enforced at the base class |
| Distributed lock key with no expiry | Process crash leaves lock held indefinitely | All Redis distributed lock keys must have `EXNX` expiry set at acquisition; lock timeout = run max duration + buffer |
| Capability model bypass: global policies have no capability filter | A high-cost LLM-backed global policy runs even on internal maintenance steps | Capability model is applied to global policies as well; steps declare `required_capabilities`; engine skips irrelevant policies |

---

## "Looks Done But Isn't" Checklist

- [ ] **Transactional persistence:** Lock acquire/release tested across the PENDING → RUNNING → step transitions; confirm no deadlock on the two `_persist_state` calls in `run_workflow` before `_advance`.
- [ ] **Policy fault isolation:** Timeout tested with a policy that internally swallows `CancelledError`; confirm timeout fires and engine continues with correct audit event.
- [ ] **Contract versioning:** Zeroth's existing version string formats (`"v2-alpha"` style) round-trip through GovernAI's `ContractVersion` without normalization errors.
- [ ] **AgentSpec/ToolManifest:** Zeroth's existing flow construction (`GovernedFlowSpec` with imperative agent wiring) passes unchanged; no new required fields on `GovernedStepSpec`.
- [ ] **RunState changes (all phases):** Old-format `RunState` JSON (from a v0.2.2 snapshot) deserializes without `ValidationError` through the new model.
- [ ] **Rich thread lifecycle:** Thread lifecycle state and `RunStatus` cannot get into a contradictory combination (e.g., thread ARCHIVED but run RUNNING); add a cross-model invariant test.
- [ ] **Secrets context:** Emit an audit event with a known secret value in the payload; assert persisted payload contains `"[REDACTED]"`, not the actual value.
- [ ] **Audit enrichment:** Old `AuditEvent` JSON (no `extensions` field) deserializes to `extensions=[]` without error.
- [ ] **Interrupt TTL:** Resume after TTL expiry raises `InterruptExpiredError` (not `ValueError` or `KeyError`) and emits `INTERRUPT_EXPIRED` audit event before `RUN_FAILED`.
- [ ] **Memory connector:** Synchronous backend implementation passes CI but `PYTHONASYNCIODEBUG=1` does not report event loop blocking > 100ms.
- [ ] **Redis key schema:** All new Redis keys use documented prefixes; KEYS scan shows no unexpected entries after a full workflow run.
- [ ] **Public API (`__all__`):** Every new public symbol is added to `__all__` in `governai/__init__.py`; no symbol is removed from `__all__` without a deprecation path.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| RunState subclass breaks Zeroth deserialize | HIGH | Add missing default to new field; publish patch release; Zeroth must flush Redis state for in-flight runs (cannot deserialize mid-flight runs from old format if validator raises) |
| Async deadlock in persistence lock | HIGH | Remove instance-wide lock; replace with per-run-id lock map; requires runtime restart to clear deadlocked tasks |
| Secret leaked into audit event | HIGH | Rotate the leaked credential immediately; add redaction pass to `AuditEmitter`; republish patched version; consider audit log purge for affected run IDs |
| Redis key namespace collision | MEDIUM | Rename conflicting keys with a migration script; requires a maintenance window if thread lifecycle keys collide with run checkpoint indexes |
| deepcopy performance regression | MEDIUM | Identify and move large payloads out of `RunState.artifacts` to a content-addressed store; checkpoints can be rewritten on next run |
| AgentSpec breaks GovernedStepSpec construction | HIGH | Revert AgentSpec to additive-only; re-examine which fields are required vs optional; requires Zeroth to pin to previous GovernAI version until fixed |
| InterruptExpiredError surfaces as untyped ValueError | LOW | Add typed exception and catch in `resume_workflow`; backward compatible change; no Redis migration needed |
| Memory connector blocks event loop | MEDIUM | Add `blocking_io=True` flag to offending backend; wrap in `asyncio.to_thread` at the runtime call site; no data migration needed |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| RunState subclass breaks Zeroth | Rich thread lifecycle + Secrets context (any phase adding RunState fields) | Deserialize v0.2.2 RunState JSON fixture through new model; assert no ValidationError |
| Async deadlock in persistence lock | Transactional state persistence | Run `run_workflow` under asyncio debug mode; assert no lock timeout; confirm two `_persist_state` calls complete without hang |
| Policy timeout swallows CancelledError | Policy fault isolation + capability model | Test with a policy that catches `BaseException`; assert `PolicyDeniedError` raised within timeout window |
| deepcopy performance | All phases adding RunState fields (establish rule in first phase) | Benchmark `run_workflow` with 10-step workflow and 100KB artifacts; assert step latency < 50ms |
| Redis key space pollution | Before first new Redis-backed store (transactional persistence or thread lifecycle) | Enumerate all Redis keys after full workflow run; assert all match documented schema |
| Secrets leaked into audit | Secrets-aware execution context | Emit audit event with known secret in payload; assert persisted value is `"[REDACTED]"` |
| AuditEvent schema breaks old events | Audit event enrichment protocol | Deserialize old AuditEvent JSON (no extensions field); assert `extensions == []` |
| Interrupt TTL race with resume | Interrupt TTL enforcement | Expire an interrupt between `get_pending` and `resolve`; assert `InterruptExpiredError` raised and `INTERRUPT_EXPIRED` event emitted |
| AgentSpec breaks existing construction | AgentSpec + ToolManifest | Run Zeroth's existing flow construction tests against updated GovernAI without changes to Zeroth |
| Contract versioning vs Zeroth registry | Contract versioning | Round-trip Zeroth's existing version string formats through GovernAI's ContractVersion model |
| Memory connector blocks event loop | Memory connector protocol | Run connector call with `PYTHONASYNCIODEBUG=1`; assert no blocking coroutine warnings |
| Public API surface broken | Every phase | Run `python -c "import governai; assert 'NewSymbol' in dir(governai)"` and verify no existing `__all__` symbols are removed |

---

## Sources

- GovernAI codebase (directly inspected): `governai/runtime/local.py`, `governai/runtime/run_store.py`, `governai/runtime/interrupts.py`, `governai/models/run_state.py`, `governai/models/audit.py`, `governai/policies/engine.py`, `governai/__init__.py`
- [redis-py Issue #3847: Async lock deadlock on cancel during release](https://github.com/redis/redis-py/issues/3847) — MEDIUM confidence (GitHub issue, not official docs)
- [Redis Distributed Locks Official Documentation](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/) — HIGH confidence
- [Python asyncio Coroutines and Tasks — TimeoutError and CancelledError propagation](https://docs.python.org/3/library/asyncio-task.html) — HIGH confidence
- [CPython Issue #133747: asyncio.TaskGroup uncancellation in 3.12 inconsistency](https://github.com/python/cpython/issues/133747) — MEDIUM confidence
- [Codeflash: Why Python's deepcopy Can Be So Slow](https://www.codeflash.ai/blog-posts/why-pythons-deepcopy-can-be-so-slow-and-how-to-avoid-it) — MEDIUM confidence (benchmark data, not official)
- [Pydantic v2 model_validate_json discriminated union behavior](https://docs.pydantic.dev/latest/concepts/models/) — HIGH confidence
- [Redis Anti-Patterns: TTL and Key Expiry](https://redis.io/tutorials/redis-anti-patterns-every-developer-should-avoid/) — HIGH confidence
- GovernAI PROJECT.md — HIGH confidence (first-party)

---
*Pitfalls research for: Adding governance depth features to GovernAI async Python workflow framework*
*Researched: 2026-04-05*
