# Architecture Research

**Domain:** Governed AI workflow framework — v0.3.0 governance depth integration
**Researched:** 2026-04-05
**Confidence:** HIGH — based on direct codebase analysis of all affected modules

---

## Existing Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         App Layer (governai/app/)                    │
│  GovernedFlow  GovernedFlowSpec  GovernedStepSpec  TransitionSpec   │
│  DSL  FlowConfigV1  GovernedFlow.from_*                             │
├─────────────────────────────────────────────────────────────────────┤
│                    Runtime Core (governai/runtime/)                  │
│   LocalRuntime._advance() — ~400-line deterministic execution loop  │
│   ExecutionContext  InterruptManager  ReducerRegistry               │
├───────────────┬─────────────────┬──────────────────┬───────────────┤
│  Policies     │   Approvals     │     Audit        │   Agents      │
│  PolicyEngine │ ApprovalEngine  │ AuditEmitter     │ Agent         │
│  PolicyContext│ ApprovalRequest │ emit_event()     │ AgentRegistry │
│  run_policy() │                 │ AuditEvent       │ AgentExecCtx  │
├───────────────┴─────────────────┴──────────────────┴───────────────┤
│                       Tools (governai/tools/)                        │
│   Tool[In,Out]  PythonTool  CLITool  ToolRegistry                  │
│   ExecutionPlacement  ToolValidationError                           │
├─────────────────────────────────────────────────────────────────────┤
│            Persistence (governai/runtime/{run_store,interrupts}.py) │
│   RunStore (ABC)  InMemoryRunStore  RedisRunStore                   │
│   InterruptStore  InMemoryInterruptStore  RedisInterruptStore        │
│   ThreadAwareRunStore (Protocol)                                     │
├─────────────────────────────────────────────────────────────────────┤
│               Models (governai/models/)                              │
│   RunState  RunStatus  AuditEvent  PolicyContext  ApprovalRequest   │
│   EventType  DeterminismMode  ResumePayload  Command                │
├─────────────────────────────────────────────────────────────────────┤
│       Execution & Extensions (governai/execution/, extensions/)      │
│   AsyncBackend  ThreadPoolBackend  ProcessPoolBackend               │
│   RemoteExecutionAdapter  HTTPSandboxExecutionAdapter               │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities (current)

| Component | Responsibility | Key Files |
|-----------|----------------|-----------|
| `LocalRuntime` | Deterministic execution loop, run lifecycle, persistence orchestration | `runtime/local.py` |
| `RunStore` | Run state and checkpoint persistence (in-memory + Redis) | `runtime/run_store.py` |
| `InterruptManager` | TTL-aware interrupt lifecycle, epoch guard | `runtime/interrupts.py` |
| `PolicyEngine` | Policy registration, evaluation chain | `policies/engine.py` |
| `ApprovalEngine` | Approval request/decision lifecycle | `approvals/engine.py` |
| `AuditEmitter` | Async event emission (in-memory + Redis) | `audit/emitter.py` |
| `Tool[In,Out]` | Typed, validated, bounded tool execution | `tools/base.py` |
| `Agent` | Bounded multi-turn LLM executor | `agents/base.py` |
| `GovernedFlowSpec` | Serializable flow definition (app layer) | `app/spec.py` |
| `ExecutionContext` | Per-step artifact + channel snapshot | `runtime/context.py` |
| `RunState` | Full mutable run snapshot (persisted) | `models/run_state.py` |

---

## New Features: Integration Analysis

### Feature 1: Transactional State Persistence

**What it is:** Atomic persist-then-cache semantics with distributed locking — prevents race conditions when two resume calls touch the same run.

**Current state:** `RunStore.put()` is non-atomic. `LocalRuntime._persist_state()` calls `run_store.put()` directly, then updates in-memory `self._runs[run_id]`. A crash between the two leaves the cache stale.

**Integration points:**
- `runtime/run_store.py` — `RunStore` ABC needs a `lock()` context manager protocol (optional, implementations may no-op). `RedisRunStore` implements it with Redis `SET NX` or Lua scripts.
- `runtime/local.py` — `_persist_state()` must acquire lock before write, release after in-memory sync. Lock acquisition must be a no-op when store does not implement locking.
- `models/run_state.py` — No changes needed. The locking contract lives at the store layer.

**New module needed:** None. Modify `RunStore` ABC (add optional `lock()` context manager) and `RedisRunStore`. `LocalRuntime._persist_state()` is the call site.

**Backward compatibility:** `lock()` is optional on `RunStore`. Existing `InMemoryRunStore` no-ops it. No API surface changes.

---

### Feature 2: Policy Fault Isolation + Capability Model

**What it is:** Per-policy timeout and exception boundaries so a misbehaving policy cannot hang or crash the entire run. Capability model lets policies declare what system privileges they require.

**Current state:** `PolicyEngine.evaluate()` calls `run_policy()` in a plain `for` loop. Any exception propagates immediately. No timeout. No capability check.

**Integration points:**
- `policies/engine.py` — `evaluate()` must wrap each `run_policy()` call with `asyncio.wait_for()` and a `try/except`. On timeout or exception, policy produces a deny decision with a fault payload (not a crash).
- `policies/base.py` — `PolicyFunc` signature stays the same. Add a `PolicyMeta` dataclass (name, timeout_seconds, required_capabilities) that `@policy` decorator attaches as `__policy_meta__`.
- `models/policy.py` — `PolicyDecision` adds an optional `fault: str | None` field for fault reporting.
- `policies/decorators.py` — `@policy` decorator reads `timeout_seconds` and `capabilities` kwargs, attaches `__policy_meta__`.
- `runtime/local.py` — `PolicyContext.capabilities` already exists. Policy capability check happens in `evaluate()` before execution: if the policy requires a capability the context does not have, skip or deny.

**New module needed:** None. All changes to `policies/engine.py`, `policies/base.py`, `policies/decorators.py`, `models/policy.py`.

**Backward compatibility:** `PolicyDecision.fault` is optional (defaults `None`). `@policy` gains optional kwargs but existing decorators without them continue to work.

---

### Feature 3: Contract Versioning

**What it is:** `version` and `min_compatible_version` on `Tool` and `GovernedStepSpec` — lets Zeroth's Studio serialize and deserialize contracts across schema versions.

**Current state:** `Tool.__init__()` has no version fields. `GovernedStepSpec` is a bare dataclass with no version. Zeroth implements this in a parallel `contracts/registry.py`.

**Integration points:**
- `tools/base.py` — Add `version: str = "1.0.0"` and `min_compatible_version: str = "1.0.0"` to `Tool.__init__()`. Add `is_compatible_with(version: str) -> bool` helper.
- `app/spec.py` — Add `version: str = "1.0.0"` to `GovernedStepSpec` and `GovernedFlowSpec`.
- `models/common.py` — Add a `parse_semver()` utility for version comparison.
- `app/flow.py` — `GovernedFlow.__init__()` validates step spec versions against tool versions at construction time (warn or raise on mismatch).

**New module needed:** None. Possibly a `governai/versioning.py` utility if semver parsing is non-trivial, but a 10-line helper in `models/common.py` is sufficient.

**Backward compatibility:** All new fields have defaults. Existing `Tool(...)` and `GovernedStepSpec(...)` constructions continue without change.

---

### Feature 4: AgentSpec (Serializable Agent Asset Definition)

**What it is:** A pure-data Pydantic model that captures all agent configuration without the runtime handler callable — serializable to JSON, storable, loadable by Zeroth Studio.

**Current state:** `Agent` is a runtime class that holds a `handler: AgentHandler` callable. It cannot be serialized. Zeroth works around this in `execution_units/adapters.py`.

**Integration points:**
- `agents/base.py` — Add `AgentSpec(BaseModel)` alongside `Agent`. `AgentSpec` captures name, description, instruction, input/output schema refs, allowed_tools, allowed_handoffs, max_turns, max_tool_calls, tags, capabilities, side_effect, execution_placement. No handler.
- `agents/base.py` — Add `Agent.to_spec() -> AgentSpec` and `Agent.from_spec(spec, handler) -> Agent` factory.
- `app/spec.py` — `GovernedStepSpec.agent` currently accepts `Any`. Add a `AgentSpec | Agent` union type hint (runtime accepts either, `GovernedFlow` resolves `AgentSpec` to `Agent` via registry at build time).

**New module needed:** `agents/spec.py` is cleaner than adding to `agents/base.py` if `AgentSpec` is large, but a single file is fine given the fields are straightforward.

**Backward compatibility:** `Agent` class unchanged. `AgentSpec` is additive. `GovernedStepSpec.agent` already typed as `Any` so runtime duck-typing continues.

---

### Feature 5: ToolManifest (Declarative, Serializable Tool Definition)

**What it is:** A Pydantic model that captures all tool metadata (including JSON Schema for input/output) without requiring an import of the actual tool class — enables Zeroth Studio to list available tools before instantiation.

**Current state:** `Tool` holds `input_model` and `output_model` as live Pydantic class references. To get the schema you must import the class.

**Integration points:**
- `tools/base.py` — Add `ToolManifest(BaseModel)` with name, description, version, executor_type, execution_placement, capabilities, tags, side_effect, requires_approval, input_schema (JSON Schema dict), output_schema (JSON Schema dict).
- `tools/base.py` — Add `Tool.to_manifest() -> ToolManifest`. Calls `self.input_model.model_json_schema()` and `self.output_model.model_json_schema()`.
- `tools/registry.py` — `ToolRegistry.list_manifests() -> list[ToolManifest]` for enumeration without instantiation.
- `app/spec.py` — `GovernedStepSpec.tool` currently `Any`. Can accept `ToolManifest` for spec-only flows (no executor), with validation that a live `Tool` is resolved before execution.

**New module needed:** `tools/manifest.py` for clean separation, or inline in `tools/base.py`. Given `ToolManifest` will be imported by Zeroth Studio directly, a separate `tools/manifest.py` is preferable for import hygiene.

**Backward compatibility:** Additive. `Tool` gains a `to_manifest()` method. `ToolRegistry` gains a `list_manifests()` method.

---

### Feature 6: Rich Thread Lifecycle Model

**What it is:** Thread-level state machine (active, paused, archived, closed) with multi-run association, metadata, and lifecycle event audit — currently threads exist only as foreign keys on `RunState.thread_id`.

**Current state:** Thread identity is `RunState.thread_id` (a string). `ThreadAwareRunStore` tracks active/latest run per thread. No thread-level metadata, status, or lifecycle events.

**Integration points:**
- New model: `models/thread.py` — `ThreadState(BaseModel)` with thread_id, status (ThreadStatus enum: active/paused/archived/closed), created_at, updated_at, metadata, run_ids.
- New store protocol: `runtime/thread_store.py` — `ThreadStore` ABC with `get`, `put`, `list_runs`, `archive`, `close` methods. `InMemoryThreadStore` and `RedisThreadStore` implementations.
- `runtime/local.py` — `run_workflow()` creates/updates a `ThreadState` entry. `resume_workflow()` checks thread status before resuming (reject if archived/closed). Add `archive_thread()` and `close_thread()` public methods.
- `models/common.py` — Add `ThreadStatus` enum.
- `audit/emitter.py` or `models/common.py` — New `EventType` values: `THREAD_CREATED`, `THREAD_ARCHIVED`, `THREAD_CLOSED`.

**New modules needed:**
- `models/thread.py` — `ThreadState`, `ThreadStatus`
- `runtime/thread_store.py` — `ThreadStore` ABC, `InMemoryThreadStore`, `RedisThreadStore`

**Backward compatibility:** `LocalRuntime.__init__()` gains an optional `thread_store` kwarg. When `None`, thread lifecycle events are skipped (backward-compatible default). Existing callers unaffected.

---

### Feature 7: Secrets-Aware Execution Context

**What it is:** Runtime resolution of secrets from a pluggable backend, injected into `ExecutionContext` and automatically redacted from audit event payloads.

**Current state:** `ExecutionContext` has artifacts, channels, and metadata. No secrets namespace. Audit payloads are emitted verbatim — no redaction.

**Integration points:**
- New protocol: `governai/secrets/` — `SecretProvider` Protocol with `async get(key: str) -> str | None`. `EnvSecretProvider` (reads `os.environ`), `DictSecretProvider` (for tests).
- `runtime/context.py` — `ExecutionContext.__init__()` gains optional `secret_provider: SecretProvider | None`. Add `async get_secret(key: str) -> str` method (raises `KeyError` if not found). Context is not async today — `get_secret` forces async context awareness at call site.
- `audit/emitter.py` — `emit_event()` gains an optional `redact_keys: set[str] | None` param. When provided, any matching keys in `payload` are replaced with `"[REDACTED]"`.
- `runtime/local.py` — `_build_execution_context()` passes `secret_provider` from `LocalRuntime` config. `_emit_audit_event()` passes `redact_keys` from the runtime's secret provider.
- `LocalRuntime.__init__()` — gains optional `secret_provider: SecretProvider | None`.

**New modules needed:**
- `governai/secrets/__init__.py`
- `governai/secrets/base.py` — `SecretProvider` Protocol, `SecretNotFoundError`
- `governai/secrets/env.py` — `EnvSecretProvider`

**Backward compatibility:** All new params are optional. Existing `ExecutionContext(...)` constructions work unchanged. `emit_event()` with no `redact_keys` emits verbatim as before.

---

### Feature 8: Audit Event Enrichment Protocol

**What it is:** Typed extension metadata on `AuditEvent` — allows Zeroth and other consumers to attach domain-specific structured data (e.g., cost metrics, model info, span IDs) without polluting the `payload` dict.

**Current state:** `AuditEvent.payload` is `dict[str, Any]`. All enrichment goes into an untyped dict. No protocol for typed extension.

**Integration points:**
- `models/audit.py` — Add `extensions: dict[str, Any] = Field(default_factory=dict)` to `AuditEvent`. This is the typed-extension slot. Each consumer registers an extension namespace key (e.g., `"zeroth"`, `"opentelemetry"`).
- `audit/emitter.py` — `emit_event()` gains an `extensions: dict[str, Any] | None` param, passed through to `AuditEvent(extensions=...)`.
- New protocol: `audit/enrichment.py` — `AuditEnricher` Protocol with `async enrich(event: AuditEvent) -> dict[str, Any]` returning the extension dict. `LocalRuntime` accepts a list of enrichers.
- `runtime/local.py` — `_emit_audit_event()` calls enrichers after event construction, merges results into `event.extensions` before emission.

**New modules needed:**
- `governai/audit/enrichment.py` — `AuditEnricher` Protocol

**Backward compatibility:** `AuditEvent.extensions` defaults to empty dict. `emit_event()` `extensions` param defaults to `None`. Existing emitter calls work unchanged.

---

### Feature 9: Interrupt TTL Enforcement

**What it is:** Runtime-enforced expiration checks at resume time, plus background cleanup of stale interrupts. Currently TTL is stored on `InterruptRequest.expires_at` and checked in `InterruptManager.get_pending()` and `resolve()`, but not enforced at the `LocalRuntime` level during resume.

**Current state:** `InterruptManager` already stores `expires_at` and checks it in `get_pending()` and `resolve()`. However, `LocalRuntime._resume_interrupt()` calls `_interrupt_resolve()` which can raise `ValueError` on expiry — but the expired interrupt is not cleaned from the store, and no systematic sweep occurs.

**Integration points:**
- `runtime/interrupts.py` — `InterruptManager.clear_expired()` already exists but is not called proactively. Add `async sweep(run_id: str)` that calls `clear_expired()` and emits `INTERRUPT_EXPIRED` audit events for each removed interrupt.
- `runtime/local.py` — Call `_interrupt_clear_expired()` at the start of `_resume_interrupt()` and at run start. Add a `purge_stale_interrupts(run_id: str)` public method.
- `models/common.py` — Add `INTERRUPT_EXPIRED_STALE` to `EventType` (distinct from `INTERRUPT_EXPIRED` which is already used for expired-at-resolve-time).

**New modules needed:** None. Changes confined to `runtime/interrupts.py` and `runtime/local.py`.

**Backward compatibility:** `InterruptManager` behavior is unchanged for non-expired interrupts. `sweep()` is additive.

---

### Feature 10: Memory Connector Protocol

**What it is:** Pluggable memory backends (vector stores, conversation history, key-value) with scope binding (per-thread, per-run, global) and automatic audit integration.

**Current state:** No memory abstraction in GovernAI. Zeroth implements this in `memory/` as a parallel system.

**Integration points:**
- New package: `governai/memory/` — Full new module.
  - `base.py` — `MemoryConnector` Protocol with `async store(key, value, scope) -> None`, `async retrieve(key, scope) -> Any | None`, `async search(query, scope, limit) -> list`. `MemoryScope` enum: `thread`, `run`, `global`.
  - `dict_connector.py` — `DictMemoryConnector` for tests (in-memory dict, scoped by thread_id/run_id/global key).
  - `context.py` — `MemoryContext` wrapper that binds a connector with a fixed scope (thread_id, run_id) for easy use inside step handlers.
- `runtime/context.py` — `ExecutionContext.__init__()` gains optional `memory: MemoryContext | None`. Add `ctx.memory.store()` and `ctx.memory.retrieve()` as the public surface.
- `runtime/local.py` — `LocalRuntime.__init__()` gains optional `memory_connector: MemoryConnector | None`. `_build_execution_context()` wraps it in `MemoryContext(connector, thread_id=state.thread_id, run_id=state.run_id)`.
- `audit/emitter.py` or `runtime/local.py` — Memory store/retrieve operations emit audit events (`MEMORY_STORED`, `MEMORY_RETRIEVED`) when `audit_memory_ops: bool = False` is set on `LocalRuntime`.
- `models/common.py` — Add `MEMORY_STORED`, `MEMORY_RETRIEVED` to `EventType`.

**New modules needed:**
- `governai/memory/__init__.py`
- `governai/memory/base.py` — `MemoryConnector` Protocol, `MemoryScope`, `MemoryContext`
- `governai/memory/dict_connector.py` — `DictMemoryConnector`

**Backward compatibility:** All new `LocalRuntime` params optional. `ExecutionContext.memory` is `None` when no connector configured. Step handlers that don't use memory are unaffected.

---

## Dependency Map Between the 10 Features

```
Contract Versioning (3)
    └── required by: AgentSpec (4), ToolManifest (5)
    └── required by: Rich Thread Lifecycle (6) [version on ThreadState]

AgentSpec (4) + ToolManifest (5)
    └── independent of each other
    └── both required before Zeroth Studio authoring unblocks

Transactional Persistence (1)
    └── independent — touches only RunStore + LocalRuntime._persist_state()

Policy Fault Isolation + Capabilities (2)
    └── independent — touches only PolicyEngine + policies/

Secrets Context (7)
    └── depends on: ExecutionContext exists (already does)
    └── required by: Audit Enrichment (8) [redaction is part of enrichment]

Audit Enrichment (8)
    └── depends on: Secrets Context (7) [redaction is part of the protocol]
    └── independent otherwise

Interrupt TTL (9)
    └── independent — incremental hardening of existing InterruptManager

Memory Connectors (10)
    └── depends on: Secrets Context (7) [memory backends may need credentials]
    └── depends on: Audit Enrichment (8) [memory ops emit typed audit events]

Rich Thread Lifecycle (6)
    └── independent of all others (new ThreadStore + ThreadState)
    └── enhanced by: Audit Enrichment (8) [thread events get extension metadata]
```

---

## Recommended Module Changes: New vs Modified

### New Modules

| Module | Purpose | Feature |
|--------|---------|---------|
| `governai/secrets/__init__.py` | Public exports | 7 |
| `governai/secrets/base.py` | `SecretProvider` Protocol, `SecretNotFoundError` | 7 |
| `governai/secrets/env.py` | `EnvSecretProvider` | 7 |
| `governai/memory/__init__.py` | Public exports | 10 |
| `governai/memory/base.py` | `MemoryConnector` Protocol, `MemoryScope`, `MemoryContext` | 10 |
| `governai/memory/dict_connector.py` | `DictMemoryConnector` (test impl) | 10 |
| `governai/audit/enrichment.py` | `AuditEnricher` Protocol | 8 |
| `governai/models/thread.py` | `ThreadState`, `ThreadStatus` | 6 |
| `governai/runtime/thread_store.py` | `ThreadStore` ABC, `InMemoryThreadStore`, `RedisThreadStore` | 6 |
| `governai/tools/manifest.py` | `ToolManifest` | 5 |

### Modified Modules

| Module | What Changes | Feature(s) |
|--------|-------------|-----------|
| `governai/models/run_state.py` | No changes required | — |
| `governai/models/common.py` | Add `ThreadStatus`, new `EventType` values, `parse_semver()` | 3, 6, 9, 10 |
| `governai/models/audit.py` | Add `extensions: dict[str, Any]` field | 8 |
| `governai/models/policy.py` | Add `fault: str | None` to `PolicyDecision` | 2 |
| `governai/tools/base.py` | Add `version`, `min_compatible_version`, `to_manifest()` | 3, 5 |
| `governai/tools/registry.py` | Add `list_manifests()` | 5 |
| `governai/agents/base.py` | Add `AgentSpec`, `to_spec()`, `from_spec()` (or `agents/spec.py`) | 4 |
| `governai/app/spec.py` | Add `version` to `GovernedFlowSpec`/`GovernedStepSpec` | 3 |
| `governai/policies/engine.py` | Wrap `run_policy()` with timeout + fault isolation | 2 |
| `governai/policies/base.py` | Add `PolicyMeta` dataclass | 2 |
| `governai/policies/decorators.py` | `@policy` reads `timeout_seconds`, `capabilities` | 2 |
| `governai/audit/emitter.py` | Add `extensions`, `redact_keys` params to `emit_event()` | 7, 8 |
| `governai/runtime/context.py` | Add `secret_provider`, `memory` to `ExecutionContext` | 7, 10 |
| `governai/runtime/interrupts.py` | Add `sweep()` to `InterruptManager` | 9 |
| `governai/runtime/run_store.py` | Add optional `lock()` context manager to `RunStore` ABC, implement in `RedisRunStore` | 1 |
| `governai/runtime/local.py` | Integrate all features via `LocalRuntime.__init__()` kwargs, `_persist_state()`, `_emit_audit_event()`, `_build_execution_context()` | 1, 2, 6, 7, 8, 9, 10 |
| `governai/__init__.py` | Export all new public symbols | all |

---

## Recommended Build Order

Dependencies and integration risk drive this order. Each phase is independently testable.

### Phase 1: Foundation Models (no runtime changes, pure data)
Build first because everything else depends on these types being stable.

1. **Contract Versioning** (`tools/base.py`, `app/spec.py`, `models/common.py`) — adds fields with defaults, zero risk
2. **ToolManifest** (`tools/manifest.py`, `tools/registry.py`) — depends on Tool.version from step 1
3. **AgentSpec** (`agents/spec.py` or `agents/base.py`) — depends on nothing, pure data model
4. **Audit Enrichment model** (`models/audit.py` — `extensions` field only) — AuditEvent change needed by everything that emits

All four can be built in parallel. They touch different files with no cross-dependencies.

### Phase 2: Isolated Protocol Definitions (no runtime wiring)

5. **Secrets Protocol** (`secrets/base.py`, `secrets/env.py`) — Protocol + one impl, no callers yet
6. **Memory Protocol** (`memory/base.py`, `memory/dict_connector.py`) — Protocol + one impl, no callers yet
7. **Policy Fault Isolation** (`policies/engine.py`, `policies/base.py`, `policies/decorators.py`, `models/policy.py`) — self-contained within the policy subsystem

Steps 5, 6, 7 can be built in parallel. They define the shape without wiring into runtime.

### Phase 3: Persistence Layer

8. **Transactional Persistence** (`runtime/run_store.py`) — add lock protocol to `RunStore` ABC and `RedisRunStore`. `InMemoryRunStore` no-ops. Wire `LocalRuntime._persist_state()`.
9. **Thread Lifecycle** (`models/thread.py`, `runtime/thread_store.py`) — new ThreadState + ThreadStore. Wire into `LocalRuntime.run_workflow()` and `resume_workflow()`.

Step 8 before step 9 is not strictly required but 8 is simpler — do it first to establish the pattern.

### Phase 4: Interrupt TTL

10. **Interrupt TTL enforcement** (`runtime/interrupts.py`, `runtime/local.py`) — add `sweep()`, wire into resume and run start. Depends on nothing new.

### Phase 5: Context Enrichment (runtime wiring of protocols)

11. **Secrets Context** (`runtime/context.py`, `runtime/local.py`) — wire `SecretProvider` into `ExecutionContext`, `LocalRuntime` gets `secret_provider` kwarg
12. **Audit Enrichment protocol** (`audit/enrichment.py`, `audit/emitter.py`, `runtime/local.py`) — add enricher protocol, redaction, wire into `_emit_audit_event()`

Step 11 before 12 because redaction is part of the audit enrichment story — secrets inform what to redact.

### Phase 6: Memory Connectors

13. **Memory Connectors** (`memory/`, `runtime/context.py`, `runtime/local.py`) — wire `MemoryConnector` into `ExecutionContext.memory`, `LocalRuntime` gets `memory_connector` kwarg. Depends on secrets (credentials for backends) and audit enrichment (memory op events).

### Phase 7: Public API Exports

14. **`governai/__init__.py` update** — export all new symbols from all phases. Write at the end to avoid import errors during development.

---

## Architectural Patterns to Follow

### Pattern 1: Protocol + No-Op Default

All new injectable dependencies (SecretProvider, MemoryConnector, AuditEnricher, ThreadStore) follow the same shape: define a `Protocol` or `ABC`, default to `None` in `LocalRuntime.__init__()`, guard usages with `if self.memory_connector is not None`.

This is the pattern already used for `remote_execution_adapter`, `interrupt_store`, and `run_store`.

### Pattern 2: Additive Model Fields with Defaults

New fields on `RunState`, `AuditEvent`, `PolicyDecision` all use `Field(default=...)` or `= None`. Pydantic v2 model validation ignores unknown fields by default in most configurations — but more importantly, all serialized snapshots already in Redis will deserialize cleanly because the new fields have defaults.

### Pattern 3: ABC for Store, Protocol for Provider

GovernAI distinguishes: persistence backends (RunStore, InterruptStore, ThreadStore) use `ABC` with `@abstractmethod` — these are framework-internal and must be subclassed. Pluggable providers (SecretProvider, MemoryConnector, AuditEnricher) use `Protocol` — these are consumer-facing and duck-typed.

### Pattern 4: Fault Boundary at Engine Level, Not Policy Level

Policy fault isolation must live in `PolicyEngine.evaluate()`, not in individual `PolicyFunc` implementations. This keeps policy authors writing plain functions; the engine wraps them in `asyncio.wait_for()`. This mirrors the existing pattern where `run_policy()` in `policies/base.py` handles the sync/async dispatch without the policy knowing.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Adding Secrets to RunState

**What people do:** Store secret values in `RunState.artifacts` or `RunState.metadata` for step-to-step passing.
**Why it's wrong:** `RunState` is persisted to Redis and checkpointed. Secrets in RunState get written to audit logs and Redis in plaintext.
**Do this instead:** Secrets live in `ExecutionContext.get_secret()` only — resolved at execution time, never persisted to `RunState`.

### Anti-Pattern 2: Async ThreadStore in InterruptStore Interface

**What people do:** Make `ThreadStore` async, but `InterruptStore` is sync (due to `RedisInterruptStore` using synchronous redis client). Mixing async/sync across stores creates confusion.
**Why it's wrong:** `LocalRuntime` already bridges sync `InterruptStore` with `asyncio.get_event_loop().run_in_executor()`. Adding a second mixed-mode store doubles the confusion.
**Do this instead:** `ThreadStore` is async-first (like `RunStore`). `InterruptStore` stays sync to maintain backward compatibility.

### Anti-Pattern 3: ToolManifest as the Execution Unit

**What people do:** Build execution logic around `ToolManifest` because it's the serializable form.
**Why it's wrong:** `ToolManifest` has no executor. It's a catalog/discovery artifact, not a runtime object.
**Do this instead:** `ToolManifest` is read-only metadata. Runtime always resolves to a live `Tool` instance via `ToolRegistry` before execution.

### Anti-Pattern 4: Memory Connector as Workflow State

**What people do:** Use `MemoryConnector.store()` to pass data between steps instead of `RunState.artifacts`.
**Why it's wrong:** Memory connector operations bypass the deterministic artifact system. `RunState.artifacts` is the replay-safe, checkpointed state carrier.
**Do this instead:** Use `ctx.memory` for long-horizon, cross-thread semantic memory. Use `ctx.get_artifact()` / `state.artifacts` for within-run data flow.

---

## Integration Points: LocalRuntime as the Hub

`LocalRuntime` is the integration hub for all 10 features. Its `__init__()` will grow by roughly 5 new optional kwargs:

```python
class LocalRuntime:
    def __init__(
        self,
        *,
        # existing
        policy_engine, approval_engine, audit_emitter, run_store,
        execution_backend, interrupt_manager, interrupt_store,
        interrupt_max_pending, reducer_registry, channel_reducers,
        channel_defaults, containment_mode, remote_execution_adapter,
        # new in v0.3.0
        thread_store: ThreadStore | None = None,           # Feature 6
        secret_provider: SecretProvider | None = None,    # Feature 7
        audit_enrichers: list[AuditEnricher] | None = None,  # Feature 8
        memory_connector: MemoryConnector | None = None,  # Feature 10
    ) -> None:
```

The three internal methods that touch the most features:

| Method | Features Touched |
|--------|-----------------|
| `_persist_state()` | 1 (transactional lock), 6 (thread state update) |
| `_emit_audit_event()` | 7 (redaction), 8 (enrichment) |
| `_build_execution_context()` | 7 (secret_provider), 10 (memory context) |
| `run_workflow()` | 6 (ThreadStore.create), 9 (TTL sweep) |
| `resume_workflow()` | 6 (ThreadStore status check), 9 (TTL sweep) |

---

## Backward Compatibility Constraints

All changes are additive. The specific constraints:

1. **`RunStore` ABC**: Adding `lock()` must be optional. Use `contextlib.asynccontextmanager` and provide a default no-op in the ABC so existing subclasses do not break.
2. **`AuditEvent`**: `extensions` field must have `default_factory=dict`. Any consumer that reconstructs `AuditEvent` from dict will get an empty extensions dict automatically.
3. **`PolicyDecision`**: `fault` must be `None` by default. Consumers that check `decision.allow` are unaffected.
4. **`ExecutionContext`**: `secret_provider` and `memory` are keyword-only with defaults of `None`. All existing `ExecutionContext(...)` constructions pass unchanged.
5. **`Tool`**: `version` and `min_compatible_version` have string defaults (`"1.0.0"`). Existing tool definitions work without changes.
6. **`@policy` decorator**: New kwargs (`timeout_seconds`, `capabilities`) must be optional with no-argument form still working: `@policy` and `@policy(name="x")` both continue to work.
7. **`LocalRuntime`**: All 4 new kwargs are keyword-only with `None` defaults.

---

## Sources

- Direct analysis of `governai/runtime/local.py` (execution loop), `governai/runtime/run_store.py` (RunStore/RedisRunStore), `governai/runtime/interrupts.py` (InterruptManager/RedisInterruptStore)
- Direct analysis of `governai/policies/engine.py`, `governai/policies/base.py`
- Direct analysis of `governai/tools/base.py`, `governai/agents/base.py`, `governai/app/spec.py`
- Direct analysis of `governai/models/audit.py`, `governai/models/policy.py`, `governai/models/common.py`
- Direct analysis of `governai/runtime/context.py`, `governai/__init__.py`
- `.planning/PROJECT.md` — constraints, Zeroth consumer patterns, workarounds that drive consolidation requirements

---
*Architecture research for: GovernAI v0.3.0 governance depth*
*Researched: 2026-04-05*
