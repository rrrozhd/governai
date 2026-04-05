# Project Research Summary

**Project:** GovernAI v0.3.0 — Governance Depth Features
**Domain:** Python governance framework for AI agent workflows
**Researched:** 2026-04-05
**Confidence:** HIGH

## Executive Summary

GovernAI v0.3.0 adds 10 governance depth features to an existing async Python framework that is already in production use by a downstream consumer (Zeroth). The fundamental challenge is not greenfield design — nearly all 10 features have working workarounds in Zeroth's codebase today. The goal is consolidation: lift those parallel implementations into first-class GovernAI primitives so Zeroth can retire its workarounds and unblock the Studio authoring layer. Every design decision must be evaluated against two constraints simultaneously: backward compatibility with Zeroth's existing constructions and correctness guarantees that Zeroth's workarounds currently lack.

The recommended approach is additive-only development across all 10 features. No existing class constructors change signatures. No new required fields land on `RunState`, `AuditEvent`, `PolicyDecision`, or `GovernedStepSpec` without explicit defaults. New capabilities are injected via optional kwargs on `LocalRuntime`, which already serves as the integration hub for the framework. The stack requires zero new core dependencies — all 10 features are implemented using the existing `redis==7.3.0`, `pydantic==2.12.5`, `tenacity==9.1.4`, and Python 3.12+ stdlib. Optional extras (`hvac`, `boto3`/`aioboto3`) are added only for secrets backend integrations, scoped to new optional extras in `pyproject.toml`.

The primary risks are behavioral, not technological. An `asyncio.Lock` placed at the wrong scope deadlocks the runtime on re-entrant `_persist_state` calls. Secrets resolved too early flow into audit payloads and are durably persisted. Adding AgentSpec as a required field on `GovernedStepSpec` breaks all of Zeroth's existing flow definitions. A new `model_validator` on `RunState` without a default causes `ValidationError` when Zeroth reads any in-flight run from Redis after upgrade. These risks are specific and preventable — each phase must include a backward-compatibility verification test before it is considered done.

---

## Key Findings

### Recommended Stack

GovernAI v0.3.0 adds zero new core dependencies. The existing stack (`redis>=5.0.0` resolved to `7.3.0`, `pydantic>=2.7,<3` resolved to `2.12.5`, `tenacity` at `9.1.4` as a transitive dep) already provides every primitive needed. `redis.asyncio.Lock` handles distributed locking. `asyncio.wait_for()` handles per-policy timeouts. `hashlib.blake2b` handles contract fingerprinting. `typing.Protocol` with `@runtime_checkable` handles all new injectable provider interfaces (`SecretsProvider`, `MemoryConnector`, `AuditEnricher`).

Three new optional extras are added to `pyproject.toml` for secrets backends: `secrets-vault` (`hvac>=2.4.0,<3`, sync-only, wrapped with `asyncio.to_thread`), `secrets-aws` (`boto3>=1.34`), and `secrets-aws-async` (`aioboto3>=12.0`). These are not added to core dependencies and are only installed by consumers who need those specific backends.

**Core technologies already in use — new usage patterns:**
- `redis.asyncio` (redis 7.3.0): `client.lock()` for distributed locking, `pipeline(transaction=True)` for atomic writes, `expireat()` for interrupt TTL
- `pydantic` (2.12.5): `model_json_schema()` for contract fingerprinting, `ConfigDict(frozen=True)` for immutable specs
- `asyncio` (stdlib): `wait_for()` for per-policy timeout, `Lock` for in-memory path, `to_thread()` for sync backend wrapping
- `hashlib` (stdlib): `blake2b` for stable, reproducible contract schema hashing
- `typing.Protocol` (stdlib): structural subtyping for `SecretsProvider`, `MemoryConnector`, `AuditEnricher`

**What NOT to add:** `aioredlock` (unnecessary for single-process runtime), `circuitbreaker` libraries (policy isolation is timeout + exception containment, not circuit state machines), any LangGraph dependency, `structlog`/`loguru` (audit events are typed Pydantic models).

### Expected Features

Research confirms all 10 features are either table stakes (expected by production workflow framework users) or meaningful differentiators. The feature dependency graph drives a clear 4-phase ordering.

**Must have — table stakes (users expect these):**
- **Transactional state persistence** — Redis WATCH + MULTI/EXEC; `RunStore.put()` is currently non-atomic
- **Interrupt TTL enforcement** — `expires_at` already stored; enforcement just needs wiring into `LocalRuntime` resume path and a sweep API
- **Policy fault isolation** — per-policy `asyncio.wait_for` + exception containment; currently any policy exception terminates the run
- **Rich thread lifecycle model** — `ThreadRecord` with status enum; threads currently exist only as foreign keys on `RunState`
- **Secrets-aware execution context** — runtime resolution via `SecretsProvider` Protocol; redaction pass in `AuditEmitter`
- **Audit event enrichment protocol** — typed `extensions` field on `AuditEvent`; currently all enrichment goes into an untyped `payload: dict`
- **Contract versioning** — SemVer on `Tool` and `GovernedStepSpec`; Zeroth's Studio authoring is blocked on this

**Should have — differentiators:**
- **Policy capability model** — `CapabilityGrant` model; `Tool.capabilities` declared but not enforced by the policy engine
- **Serializable agent asset definitions (AgentSpec)** — `AgentSpec(BaseModel)` extracting all non-callable agent config; Zeroth Studio authoring is blocked on this
- **Execution manifest model (ToolManifest)** — `ToolManifest(BaseModel)` as the serializable, storable descriptor for a tool; Zeroth Studio is blocked on this

**Defer to v2+:**
- **Memory connector protocol** — highest complexity (HIGH rating), no hard blockers except audit enrichment; defer if scope pressure exists

**Anti-features to avoid (commonly requested but problematic):**
- Pessimistic/distributed locking on every state write (use optimistic WATCH/MULTI/EXEC instead)
- Full automatic schema migration engine (store version field; migrations are application concern, not store concern)
- Agent-level memory as part of `RunState` (unbounded growth; use memory connector protocol with explicit scoping)
- Thread archival as hard delete (use status transition + TTL; audit trail must be retained)
- Global policy timeout shared across all policies (use per-policy timeout with a default fallback)
- Secrets stored in `RunState` or audit payload (resolve at call time; redact before emit)

### Architecture Approach

`LocalRuntime` is the integration hub for all 10 features and will gain 4 new optional kwargs: `thread_store`, `secret_provider`, `audit_enrichers`, and `memory_connector`. All new injectable dependencies follow the existing "Protocol + No-Op Default" pattern already used for `remote_execution_adapter`, `interrupt_store`, and `run_store`. The three internal methods that change the most are `_persist_state()` (transactional locking + thread state update), `_emit_audit_event()` (secrets redaction + enrichment), and `_build_execution_context()` (secrets provider + memory context injection).

The architecture distinguishes two kinds of new components by interface type: persistence backends (`RunStore`, `InterruptStore`, new `ThreadStore`) use `ABC` with `@abstractmethod` since they are framework-internal; pluggable providers (`SecretProvider`, `MemoryConnector`, `AuditEnricher`) use `typing.Protocol` since they are consumer-facing and must support structural subtyping so Zeroth's existing classes do not need to inherit from GovernAI.

**Major new components:**
1. `governai/secrets/` — `SecretProvider` Protocol, `EnvSecretProvider`, `SecretNotFoundError`
2. `governai/memory/` — `MemoryConnector` Protocol, `MemoryScope`, `MemoryContext`, `DictMemoryConnector`
3. `governai/audit/enrichment.py` — `AuditEnricher` Protocol
4. `governai/models/thread.py` + `governai/runtime/thread_store.py` — `ThreadState`, `ThreadStatus`, `ThreadStore` ABC with in-memory and Redis implementations
5. `governai/tools/manifest.py` — `ToolManifest` (separate file for import hygiene; Zeroth Studio imports this directly)

**Modified modules (highest churn):**
- `governai/runtime/local.py` — integrates all 10 features (new kwargs, method changes)
- `governai/runtime/run_store.py` — optional `lock()` context manager on `RunStore` ABC
- `governai/audit/emitter.py` — `extensions` and `redact_keys` params on `emit_event()`
- `governai/models/common.py` — new `EventType` values, `ThreadStatus`, `parse_semver()`

### Critical Pitfalls

1. **Breaking Zeroth's `RunState` subclass with new model fields** — Every new field on `RunState` must have an explicit `default` or `default_factory`. New `model_validator` entries must be purely additive. Include a cross-version deserialization test using a v0.2.2-format `RunState` JSON fixture in every phase that touches `RunState`.

2. **Async deadlock from a single-instance `asyncio.Lock` in `_persist_state`** — `run_workflow` calls `_persist_state` twice before entering `_advance`, which itself calls `_persist_state` on every step. An instance-wide lock deadlocks on the second acquire. Use a per-run-id lock dict (`dict[str, asyncio.Lock]`) or acquire a distributed Redis lock once at the `run_workflow`/`resume_workflow` entry boundary, never inside the per-step helper.

3. **Secrets leaking into audit events via `payload` dict** — Secrets must travel as `SecretRef` objects (opaque references) everywhere in the framework until the moment of execution. The redaction pass must run inside `AuditEmitter.emit()` before persistence — not as a caller responsibility. Test: emit an audit event with a known secret value in payload; assert persisted payload contains `"[REDACTED]"`.

4. **`AgentSpec` or `ToolManifest` breaking existing `GovernedStepSpec` construction** — These are strictly additive models. `AgentSpec` and `ToolManifest` do not replace `Agent` and `Tool`. `GovernedStepSpec` gains only an optional `agent_spec: AgentSpec | None = None` field. Verification: Zeroth's existing flow construction must pass unchanged after this phase.

5. **`model_copy(deep=True)` performance degradation with large artifacts** — Every `RunStore.put()` call deepcopies `RunState`. Adding new fields that carry raw payloads (memory connector results, large step outputs) amplifies this O(steps × artifact_size). Rule: `RunState` fields hold IDs/references, never raw blobs. Enforce this rule before transactional persistence and memory connector phases.

6. **Redis key space collisions across new feature prefixes** — Define and document the full Redis key schema before implementing any new Redis-backed store. All new keys must follow the `governai:{feature}:{scope}:{id}` pattern with TTL on bounded-lifecycle keys. Reference schema from PITFALLS.md.

7. **Contract versioning colliding with Zeroth's existing `contracts/registry.py`** — Read Zeroth's existing version string formats before finalizing GovernAI's `ContractVersion` model. GovernAI's version model must accept Zeroth's existing strings without re-serialization. Verification: round-trip Zeroth's existing version string formats through GovernAI's model before marking the phase complete.

---

## Implications for Roadmap

Research establishes a clear 4-phase dependency ordering driven by feature cross-dependencies, Zeroth unblocking priority, and the rule that backward compatibility must be verified before new features build on top.

### Phase 1: Foundations
**Rationale:** Three features with no cross-feature dependencies, highest safety/correctness value, and all required before later phases build on top. Contract versioning unblocks AgentSpec, ToolManifest, and Zeroth Studio. Policy fault isolation is required before the capability model (capability checks run inside the fenced loop). Interrupt TTL is the lowest-complexity item with the highest immediate correctness value.
**Delivers:** Policy engine is crash-safe; interrupt deadlocks are eliminated; contract version primitives exist for Phase 2.
**Features:** Contract Versioning, Policy Fault Isolation, Interrupt TTL Enforcement
**Pitfalls to avoid:** Policy timeout must catch `asyncio.TimeoutError` explicitly, not broad `Exception`; interrupt TTL must ship `InterruptExpiredError` (typed exception) + audit event wire-up + typed catch in `resume_workflow` as one unit; contract version model must be compatible with Zeroth's existing string format before completion.
**Research flag:** Standard patterns — well-documented. Skip `research-phase` for these.

### Phase 2: Serializable Asset Layer
**Rationale:** AgentSpec and ToolManifest both require the contract versioning types from Phase 1. Transactional state persistence is required before thread lifecycle (thread status transitions are state writes that must be atomic). All three unblock or improve Zeroth directly.
**Delivers:** Zeroth Studio can serialize/deserialize agent and tool definitions; `RunStore.put()` is atomic; Zeroth's `contracts/registry.py` and `execution_units/adapters.py` workarounds can be retired.
**Features:** AgentSpec, ToolManifest, Transactional State Persistence
**Pitfalls to avoid:** AgentSpec and ToolManifest must be strictly additive — Zeroth's existing flow constructions must pass unchanged; distributed lock must be per-run-id (not instance-wide) to prevent deadlock; Redis key schema must be documented before transactional persistence ships.
**Research flag:** Standard patterns — skip `research-phase`. Transactional persistence pattern (`WATCH`/`MULTI/EXEC`) is well-documented in Redis docs and verified against existing codebase.

### Phase 3: Runtime Depth
**Rationale:** Policy capability model requires fault isolation from Phase 1. Thread lifecycle requires transactional persistence from Phase 2. Secrets context and audit enrichment are coupled (redaction is one kind of enrichment) — implement enrichment protocol first, then add redaction as a built-in enricher. All four improve runtime correctness and security materially.
**Delivers:** Policy engine enforces capability grants; thread lifecycle is tracked and auditable; secrets are resolved safely and redacted from audit events; audit events carry typed extension metadata.
**Features:** Policy Capability Model, Rich Thread Lifecycle, Secrets-Aware Execution Context, Audit Event Enrichment Protocol
**Pitfalls to avoid:** Secrets must travel as `SecretRef` (opaque references) until execution time — never in `PolicyContext.metadata` or `RunState`; thread lifecycle state must live on a separate `ThreadState` model, not embedded in `RunState`; `AuditEvent.extensions` must use `default_factory=list` so old events deserialize to `extensions=[]` without error; all new `RunState`-touching phases must include a v0.2.2 deserialization test.
**Research flag:** Secrets integration needs `research-phase` if Vault or AWS backends are prioritized for early adoption. The protocol pattern itself is standard; backend wrapping (`asyncio.to_thread` for sync `hvac`) is straightforward.

### Phase 4: Memory Layer
**Rationale:** Highest complexity feature (HIGH rating), depends on audit enrichment (memory ops emit typed audit events) and benefits from secrets context (memory backends may need credentials). No Zeroth workaround is urgently blocking on this — defer if scope pressure exists.
**Delivers:** Agents can read/write governed cross-thread memory with audit traces; `MemoryConnector` Protocol gives Zeroth a standardized interface to retire its `memory/` workaround.
**Features:** Memory Connector Protocol
**Pitfalls to avoid:** All memory connector implementations must declare `blocking_io: bool`; the runtime wraps `blocking_io=True` backends in `asyncio.to_thread` automatically; memory connector results must never be stored directly in `RunState` (hold IDs/references only); memory cache entries must carry TTL.
**Research flag:** Needs `research-phase` during planning if vector store backends are in scope for v0.3.0. The base protocol and `DictMemoryConnector` are standard. Vector store adapter patterns (LangChain `BaseChatMessageHistory` compatibility layer) need domain-specific research.

### Phase 5: Public API Exports
**Rationale:** Defer `governai/__init__.py` updates to last to avoid import errors during development. This phase is purely additive — export all new public symbols. Verify nothing was removed from `__all__` without a deprecation path.
**Delivers:** Clean public API for Zeroth and other consumers.
**Features:** `__init__.py` updates across all new modules
**Research flag:** No research needed — mechanical task.

### Phase Ordering Rationale

- Contract versioning must precede AgentSpec and ToolManifest (both carry `version` fields referencing the versioning model).
- Policy fault isolation must precede the capability model (capability checks run inside the fenced evaluation loop — adding them to an unfenced loop reintroduces the same blast-radius problem).
- Transactional state persistence must precede thread lifecycle (thread status transitions are state writes; without atomicity a transition that crashes mid-write leaves the thread in an ambiguous state).
- Audit enrichment must precede (or ship with) secrets context (redaction is implemented as a built-in enricher — the enrichment protocol must exist first).
- Memory connector must come last — it depends on both secrets and audit enrichment, and is the only feature that introduces a new category of external integration.
- The "Looks Done But Isn't" checklist from PITFALLS.md should be applied at the end of each phase before marking it complete.

### Research Flags

Phases needing deeper research during planning:
- **Phase 3 (Secrets):** If Vault or AWS Secrets Manager backends are in scope for v0.3.0, research async wrapping patterns for `hvac` (sync-only SDK) and `boto3`/`aioboto3` before implementation starts.
- **Phase 4 (Memory):** If vector store backends (Pinecone, Weaviate, pgvector) are in scope, research async adapter patterns. LangChain `BaseChatMessageHistory` compatibility layer needs design work to avoid coupling GovernAI core to LangChain types.

Phases with standard patterns (skip `research-phase`):
- **Phase 1 (Foundations):** All three features use well-documented patterns (Redis TTL, `asyncio.wait_for`, Pydantic SemVer field) verified against the locked dependency set.
- **Phase 2 (Serializable Assets):** Redis `WATCH`/`MULTI/EXEC` and Pydantic `BaseModel` serialization are standard patterns with high-confidence documentation.
- **Phase 5 (Exports):** Mechanical task with no design ambiguity.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All claims verified against installed lockfile (`uv.lock`), official Redis docs, Pydantic docs, and Python stdlib docs. Zero new core dependencies — reduces version compatibility risk to near zero. |
| Features | HIGH | Verified against LangGraph, Temporal, CrewAI, Oracle Agent Spec, Argo Workflows, Airflow, and Prefect. Feature dependency graph is internally consistent and matches architecture analysis. |
| Architecture | HIGH | Based on direct codebase analysis of all affected modules (`local.py`, `run_store.py`, `interrupts.py`, `policies/`, `audit/`, `tools/`, `agents/`, `app/`, `models/`). Integration points are specific and verified. |
| Pitfalls | HIGH | Code-inspected pitfalls (re-entrant lock deadlock, RunState subclass breakage, secrets in audit payloads) are specific to the GovernAI codebase. External patterns (Redis key schema, deepcopy performance, CancelledError swallowing) verified against official documentation and known library issues. |

**Overall confidence:** HIGH

### Gaps to Address

- **Zeroth's `contracts/registry.py` version string format:** PITFALLS.md flags that GovernAI's contract versioning model must be compatible with Zeroth's existing version strings (e.g., `"v2-alpha"` style). This needs validation against Zeroth's actual format before the contract versioning design is finalized. Read `zeroth/contracts/registry.py` at the start of Phase 1 planning.
- **Memory connector scope for v0.3.0:** Research scoped memory connector to an in-memory `DictMemoryConnector` + `RedisMemoryConnector`. If vector store backends are in-scope for v0.3.0 (not clearly established), Phase 4 complexity increases materially and needs dedicated research.
- **`RedisInterruptStore` async migration timing:** STACK.md notes `RedisInterruptStore` uses the sync `redis.Redis` client (inconsistent with `RedisRunStore`'s `redis.asyncio`). The v0.3.0 interrupt TTL work is a natural migration point. This should be confirmed as in-scope for Phase 1 to avoid carrying the sync/async inconsistency into later phases.
- **`asyncio.wait_for` + Python 3.12 `CancelledError` propagation bug:** PITFALLS.md flags a documented Python 3.12 bug where `CancelledError` propagates unexpectedly in nested `TaskGroup`/`timeout` blocks. Validate the specific GovernAI policy evaluation pattern against this bug before Phase 1 ships.

---

## Sources

### Primary (HIGH confidence)
- `uv.lock` lockfile — verified resolved versions for redis (7.3.0), pydantic (2.12.5), tenacity (9.1.4)
- [redis-py 7.4.0 Asyncio Examples](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) — pipeline `transaction=True`, `lock()` usage
- [Redis Distributed Locks official docs](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/) — single-node lock pattern vs Redlock
- [Pydantic JSON Schema docs](https://docs.pydantic.dev/latest/concepts/json_schema/) — `model_json_schema()`, `ConfigDict(frozen=True)`
- [Python asyncio-task docs](https://docs.python.org/3/library/asyncio-task.html) — `wait_for`, `shield`, `CancelledError` behavior
- [Python hashlib docs](https://docs.python.org/3/library/hashlib.html) — `blake2b` stdlib availability since Python 3.6
- [PEP 544 Protocols](https://peps.python.org/pep-0544/) — `@runtime_checkable` structural subtyping
- Direct codebase analysis — `runtime/local.py`, `runtime/run_store.py`, `runtime/interrupts.py`, `policies/engine.py`, `audit/emitter.py`, `tools/base.py`, `agents/base.py`, `app/spec.py`, `models/`

### Secondary (MEDIUM–HIGH confidence)
- [LangGraph thread lifecycle docs](https://docs.langchain.com/langsmith/use-threads) — `idle`/`busy`/`interrupted`/`error` states
- [Temporal Workflows Docs](https://docs.temporal.io/workflows) — state atomicity, activity isolation patterns
- [Oracle Open Agent Specification](https://github.com/oracle/agent-spec) — `AgentSpec` field set, `opset` versioning
- [CrewAI Agents Docs](https://docs.crewai.com/en/concepts/agents) — declarative agent YAML definitions
- [HashiCorp Vault AI Agent Identity](https://developer.hashicorp.com/validated-patterns/vault/ai-agent-identity-with-hashicorp-vault) — secrets injection pattern
- [Martin Kleppmann on distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html) — Redlock critique (single-node case)
- [LangGraph Memory Overview](https://docs.langchain.com/oss/python/langgraph/memory) — short-term vs long-term memory scoping
- [hvac 2.4.0 PyPI](https://pypi.org/project/hvac/) — sync-only, latest stable Oct 2025

---

*Research completed: 2026-04-05*
*Ready for roadmap: yes*
