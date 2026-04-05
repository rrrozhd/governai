# Feature Research

**Domain:** Governed AI workflow framework — governance depth (v0.3.0)
**Researched:** 2026-04-05
**Confidence:** HIGH (core patterns verified against LangGraph, Temporal, CrewAI, Oracle Agent Spec docs; specific GovernAI patterns verified against source)

---

## Framing

This research covers the 10 new features targeted for GovernAI v0.3.0. Each feature is evaluated against what production workflow and orchestration frameworks (Temporal, Prefect, LangGraph, CrewAI, Argo Workflows, Oracle Agent Spec) treat as table stakes vs. differentiators. Anti-features document patterns that seem attractive but create problems in practice.

The primary design constraint: Zeroth already implements parallel workarounds for all 10 features. The correct outcome is consolidation into GovernAI primitives, not a from-scratch design.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that any production governance framework is expected to have. Their absence makes GovernAI feel incomplete relative to LangGraph, Temporal, and Prefect equivalents.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Transactional state persistence** (atomic persist-then-cache) | Temporal and LangGraph both treat state writes as atomic. Without atomicity, a crash between persist and cache leaves the system inconsistent. Users expect "it either saved or it didn't." | MEDIUM | Redis WATCH + MULTI/EXEC or Lua script for atomic compare-and-swap. `put()` in `RedisRunStore` is not currently atomic. In-memory store needs no locking. Distributed lock (`SET NX PX`) is the standard Redis pattern for mutual exclusion; optimistic locking (WATCH) suits low-contention reads-then-write. |
| **Interrupt TTL enforcement** (expiration checks and stale cleanup) | Argo Workflows, LangGraph, and every human-in-the-loop system enforces TTLs. Unanswered interrupts that live forever cause deadlocks. `expires_at` already exists on `InterruptRequest`; enforcement just needs to be wired into resume paths and a cleanup sweep. | LOW | `InterruptManager` already stores `expires_at` and marks `status = "expired"` on read. What is missing: active enforcement at resume time, a scheduled sweep API, and integration with the `LocalRuntime` loop. |
| **Policy fault isolation** (per-policy timeout + exception containment) | Temporal activities are isolated by default; a crashing activity does not crash the orchestrator. Users expect policy failures to be catchable and attributable, not to bubble up as unhandled exceptions that terminate a run. | MEDIUM | Wrap each policy evaluation in `asyncio.wait_for` + broad `except Exception`. Return a `PolicyDecision(allow=False, reason="policy_timeout")` rather than letting the exception propagate. The `PolicyEngine.evaluate` loop needs try/except per policy, not around the whole batch. |
| **Rich thread lifecycle model** (states, multi-run association, archival) | LangGraph tracks thread status as `idle`, `busy`, `interrupted`, `error`. Zeroth extends `RunState` with thread metadata. A thread that accumulates runs over time needs a lifecycle — created, active, idle, interrupted, archived — or callers cannot tell whether a thread is safe to resume. | MEDIUM | Add a `ThreadRecord` model (status enum, created_at, updated_at, run_ids, metadata). Thread store methods already exist (`set_active_run_id`, `list_run_ids`). Archival = status transition + TTL/cleanup, not deletion. |
| **Secrets-aware execution context** (runtime resolution, audit redaction) | Airflow, Prefect, and HashiCorp Vault all treat secrets as late-bound references resolved at runtime, never stored inline. AI agent frameworks (2025) treat plaintext credentials in prompts as a security anti-pattern. Audit logs must redact secret values automatically. | MEDIUM | Protocol: `SecretsProvider` with `resolve(key: str) -> str`. Runtime injects into `ExecutionContext`. Audit emitter applies a redaction pass (replace known secret values with `[REDACTED]`). No secrets stored in `RunState.artifacts`. |
| **Audit event enrichment protocol** (typed extension metadata) | Structured audit logs with typed extension fields are table stakes in regulated environments. Splunk, MCP audit guidance, and enterprise governance platforms all require JSON audit records with consistent schemas and extensible fields, not freeform `payload: dict`. | LOW | Extend `AuditEvent` with an `extensions` field typed as `dict[str, BaseModel]` or a discriminated union. Define `AuditExtensionProtocol`. Emitters serialize extensions alongside the base event. No new infrastructure needed. |
| **Contract versioning** (SemVer on tools and step specs) | API versioning is table stakes for any durable interface. Pydantic v2, OpenAPI, and Oracle Agent Spec all treat schema version as a first-class field. Zeroth's `contracts/registry.py` already manages this; it belongs in GovernAI. | MEDIUM | Add `version: str` (SemVer) to `Tool` and `GovernedStepSpec`. Registry maps `(name, version)` → tool. Compatibility check: MINOR/PATCH versions are backward compatible; MAJOR is not. Migration shim: `contract_migrate(old_version, new_version, payload)`. |

### Differentiators (Competitive Advantage)

Features that distinguish GovernAI from generic orchestration frameworks. Not universally expected, but materially increase value for governed multi-agent deployments.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Policy capability model** (grant/deny per capability tag, policy scoping) | Most frameworks (Prefect, Dagster) enforce coarse RBAC at the platform level. GovernAI's governance-first model can enforce fine-grained capability checks at the tool/agent level before execution. Tools and agents already carry `capabilities: list[str]`; the policy engine does not yet check them. | MEDIUM | Add `CapabilityGrant` model (capability, scope: global/workflow/step). Policy context receives the tool's declared capabilities. A `CapabilityPolicy` checks intersection: if a required capability is not in the granted set, deny. This closes the loop between `Tool.capabilities` and actual enforcement. |
| **Serializable agent asset definitions (AgentSpec)** | Oracle's Open Agent Spec (2025), CrewAI's `agents.yaml`, and LangGraph assistants all treat agent configuration as a serializable, portable artifact separate from runtime instances. GovernAI's `Agent` class is runtime-only. Zeroth's Studio authoring layer is blocked on this. | MEDIUM | Extract `AgentSpec(BaseModel)` with all non-callable fields from `Agent.__init__`. Fields: `name`, `description`, `instruction`, `input_model_schema`, `output_model_schema`, `allowed_tools`, `allowed_handoffs`, `max_turns`, `max_tool_calls`, `capabilities`, `tags`, `requires_approval`, `execution_placement`, `version`. Factory: `Agent.from_spec(spec)`. JSON-serializable (Pydantic `model_dump_json()`). Schemas stored as `dict` (JSON Schema), not Python type references. |
| **Execution manifest model (ToolManifest)** | CrewAI and Oracle Agent Spec both distinguish "what a tool does" (declarative manifest) from "how it runs" (runtime executor). A `ToolManifest` is the serializable, storable descriptor for a tool — its schema, capabilities, placement, and version — without the Python callable. Zeroth's `execution_units/adapters.py` implements this ad-hoc. | MEDIUM | `ToolManifest(BaseModel)`: `name`, `version`, `description`, `input_schema`, `output_schema`, `capabilities`, `side_effect`, `requires_approval`, `executor_type`, `execution_placement`. Factory: `Tool.to_manifest() -> ToolManifest`. Registry can store manifests independently of live tool instances. |
| **Memory connector protocol** (scope binding, audit integration, pluggable backends) | LangGraph distinguishes short-term (thread-scoped checkpoint state) from long-term (cross-thread store, vector DB). The pattern is a protocol, not a concrete backend. GovernAI's existing channels are thread-scoped; a `MemoryConnector` protocol gives agents a governed way to read/write cross-thread memory with audit traces. | HIGH | `MemoryConnector` Protocol: `read(scope, key) -> Any`, `write(scope, key, value) -> None`, `search(scope, query) -> list`. Scopes: `thread`, `workflow`, `global`. Audit integration: memory writes emit `AuditEvent(event_type=MEMORY_WRITE)`. Backend implementations (in-memory dict, Redis hash, vector store) are optional extras. The protocol is the GovernAI primitive; backends ship separately or in Zeroth. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Distributed/pessimistic locking for every state write** | Seems like the "safe" approach to prevent concurrent modifications under load | Redis `REDLOCK` across multiple nodes is notoriously hard to get right (Kleppmann 2016 critique still applies). Pessimistic locks introduce contention, deadlock risk, and latency. GovernAI is single-process; full distributed locking is over-engineering for the current runtime model. | Optimistic locking via Redis `WATCH`/`MULTI/EXEC` for the Redis store; no locking needed for in-memory store. Add a lock interface that is optional and can be swapped if Zeroth ever scales to multi-process. |
| **Full schema migration engine** (automatic version coercion on all reads) | Contract versioning naturally leads to wanting data migration pipelines | Schema migration at read time couples the persistence layer to business logic, makes the store responsible for understanding every schema version ever written, and creates ordering dependencies that defeat the purpose of backward compatibility. | Store the `version` field. Provide a `contract_migrate(from_version, to_version, payload)` hook that callers invoke explicitly. Migration is an application concern, not a store concern. |
| **Agent-level memory as part of RunState** | Convenient to store everything in the run state dict | RunState grows unboundedly. Serialization cost scales with payload size. Large artifacts cause `deepcopy` and Redis payload issues (GovernAI constraint: "handle realistic artifact sizes without degradation"). LangGraph learned this and moved large payloads to S3. | Memory connector protocol with explicit scoping. Agents read/write memory through the protocol; RunState holds only step artifacts (bounded by step outputs). |
| **Thread archival as hard delete** | Simplest cleanup path; frees storage immediately | Deleting archived threads loses the audit trail. Compliance environments require retention windows. LangGraph's DynamoDB saver uses TTL expiry, not deletion, for this reason. | Thread archival = status transition to `archived` + optional TTL-based backend expiry. The store owns retention policy (TTL seconds); the application controls the transition trigger. |
| **Global policy timeout shared across all policies** | One config value is simpler | A slow network-call policy does not deserve the same timeout as a fast in-process check. Shared timeout either starves legitimate slow policies or fails to catch genuinely hung ones. | Per-policy timeout attribute. Default fallback timeout in `PolicyEngine`. Each policy registers with an optional `timeout_seconds` override. |
| **Secrets stored in RunState or audit payload** | Convenient for passing credentials through workflow steps | Any persistence backend that stores RunState or audit events will contain plaintext secrets. Redis TTL expiry does not help once a secret has been written to an audit log. Regulatory environments mandate that secrets never appear in logs. | SecretsProvider protocol: secrets are resolved at call time, injected into execution context as a non-persisted transient, and actively redacted from audit payloads before emit. |

---

## Feature Dependencies

```
Contract Versioning
    └──required-by──> AgentSpec (AgentSpec fields carry a version)
    └──required-by──> ToolManifest (ToolManifest has a version field)
    └──required-by──> [Zeroth Studio authoring — blocked on this]

AgentSpec
    └──requires──> Contract Versioning (version field)
    └──enhances──> ToolManifest (AgentSpec references tool names/versions)

ToolManifest
    └──requires──> Contract Versioning (version field)
    └──enhances──> AgentSpec (AgentSpec embeds tool manifest references)

Transactional State Persistence
    └──enhances──> Rich Thread Lifecycle (thread state transitions must be atomic)
    └──enhances──> Interrupt TTL Enforcement (interrupt writes should be atomic)

Policy Capability Model
    └──requires──> Policy Fault Isolation (capability checks run inside policy evaluation loop)
    └──enhances──> AgentSpec (AgentSpec declares required capabilities)
    └──enhances──> ToolManifest (ToolManifest declares provided capabilities)

Policy Fault Isolation
    └──enhances──> Policy Engine (wraps existing PolicyEngine.evaluate loop)

Rich Thread Lifecycle
    └──enhances──> Transactional State Persistence (thread status transitions are state writes)
    └──enhances──> Interrupt TTL Enforcement (TTL sweep operates per-thread)
    └──requires──> [RunStore — already exists]

Secrets-Aware Execution Context
    └──enhances──> Audit Event Enrichment (secrets redaction pass in emitter)
    └──enhances──> Memory Connector Protocol (memory writes should not persist raw secrets)

Audit Event Enrichment
    └──enhances──> Secrets-Aware Execution Context (redaction is an enrichment concern)
    └──enhances──> Memory Connector Protocol (memory writes emit enriched audit events)

Memory Connector Protocol
    └──enhances──> Audit Event Enrichment (memory ops emit typed audit events)
    └──depends-on──> [AuditEmitter — already exists]
    └──depends-on──> [RunState.channels — already exists for thread-scoped memory]

Interrupt TTL Enforcement
    └──depends-on──> [InterruptManager — already exists, expires_at already stored]
    └──depends-on──> [Rich Thread Lifecycle — sweep operates per-thread]
```

### Dependency Notes

- **Contract Versioning must ship before AgentSpec and ToolManifest**: both models carry a `version` field and reference versioned contracts. Implement versioning first.
- **Policy Fault Isolation must ship before or with the Capability Model**: capability checks run inside the policy evaluation loop. Adding capability enforcement to an unfenced loop creates the same blast-radius problem.
- **Transactional State Persistence enhances Thread Lifecycle**: thread status transitions (idle → active → interrupted → archived) are state writes. Without atomicity, a status transition that crashes mid-write leaves the thread in an ambiguous state.
- **Audit Event Enrichment and Secrets Redaction are coupled**: the redaction pass is one kind of enrichment. Implement the enrichment protocol first, then add redaction as a built-in enricher.
- **Memory Connector Protocol has no blockers but is the most complex**: it is the only feature that introduces a new category of external integration (vector stores, cross-thread state). Implement last to avoid scope creep blocking simpler features.
- **Interrupt TTL Enforcement has no cross-feature dependencies**: it is the lowest-risk item. The infrastructure (`expires_at`, `InterruptManager.clear_expired`) already exists; the work is wiring enforcement into the runtime loop.

---

## Phase Recommendations (v0.3.0)

### Phase 1 — Foundations (ship first, others depend on these)

- [ ] **Contract versioning** — unblocks AgentSpec, ToolManifest, and Zeroth Studio
- [ ] **Policy fault isolation** — required before capability model; reduces blast radius of existing engine
- [ ] **Interrupt TTL enforcement** — lowest complexity, no dependencies, high safety value

### Phase 2 — Serializable Asset Layer (requires Phase 1)

- [ ] **AgentSpec** — requires contract versioning; unblocks Studio authoring
- [ ] **ToolManifest** — requires contract versioning; pairs with AgentSpec
- [ ] **Transactional state persistence** — required before thread lifecycle

### Phase 3 — Runtime Depth (requires Phases 1–2)

- [ ] **Policy capability model** — requires policy fault isolation
- [ ] **Rich thread lifecycle** — requires transactional state persistence
- [ ] **Secrets-aware execution context** — no hard blockers, but pairs with audit enrichment
- [ ] **Audit event enrichment protocol** — pairs with secrets; no hard blockers

### Phase 4 — Memory Layer (defer until Phase 3 is stable)

- [ ] **Memory connector protocol** — highest complexity; requires audit enrichment for memory event emission

---

## Feature Prioritization Matrix

| Feature | Zeroth Value | Implementation Cost | Priority |
|---------|--------------|---------------------|----------|
| Contract versioning | HIGH (Studio blocked) | MEDIUM | P1 |
| Policy fault isolation | HIGH (safety) | MEDIUM | P1 |
| Interrupt TTL enforcement | HIGH (correctness) | LOW | P1 |
| AgentSpec | HIGH (Studio blocked) | MEDIUM | P1 |
| ToolManifest | HIGH (Studio blocked) | MEDIUM | P1 |
| Transactional state persistence | HIGH (correctness) | MEDIUM | P1 |
| Policy capability model | HIGH (governance depth) | MEDIUM | P2 |
| Rich thread lifecycle | MEDIUM (observability) | MEDIUM | P2 |
| Secrets-aware execution context | HIGH (security) | MEDIUM | P2 |
| Audit event enrichment | MEDIUM (compliance) | LOW | P2 |
| Memory connector protocol | MEDIUM (future agents) | HIGH | P3 |

**Priority key:**
- P1: Must have for v0.3.0 core; Zeroth is currently working around these with parallel systems
- P2: Should have in v0.3.0; improves correctness and security materially
- P3: Valuable architecture investment; defer if scope pressure exists

---

## Competitor Feature Analysis

| Feature | LangGraph | Temporal | CrewAI / Agent Spec | GovernAI v0.3.0 Approach |
|---------|-----------|----------|---------------------|--------------------------|
| State persistence atomicity | Checkpoint at each super-step; no explicit lock, relies on Postgres/DynamoDB transaction semantics | Event-sourcing with exactly-once semantics baked into the server | N/A (not workflow engine) | Redis WATCH + MULTI/EXEC for optimistic atomicity; optional distributed lock interface |
| Policy / capability model | No native policy engine; relies on guard nodes in the graph | Activity timeouts and retry policies; no capability model | Agent Spec declares required capabilities on tools | GovernAI `PolicyEngine` + `CapabilityGrant` model; capability enforcement per tool invocation |
| Thread lifecycle states | `idle`, `busy`, `interrupted`, `error` | Workflow status: `Running`, `TimedOut`, `Completed`, `Failed`, `Terminated` | N/A | `ThreadRecord` with `created`, `active`, `idle`, `interrupted`, `archived` |
| Secrets management | Injected via `RunnableConfig` at call time; no native redaction | Activity context carries secrets; audit logging is external concern | Not defined in spec | `SecretsProvider` protocol; runtime injection into `ExecutionContext`; emitter-level redaction |
| Serializable agent definition | "Assistants" (JSON config stored in LangGraph Platform) | `WorkflowDefinition` (code-based, not a portable data model) | Oracle Agent Spec (JSON, framework-agnostic) | `AgentSpec(BaseModel)` + `ToolManifest(BaseModel)`; JSON-serializable via Pydantic |
| Contract versioning | No native versioning on graph nodes | No tool-level versioning; workflow versioning via `WorkflowType` name | Opset version on the spec itself | SemVer on `Tool.version` and `GovernedStepSpec.version`; registry keyed on `(name, version)` |
| Audit enrichment | LangSmith traces with custom metadata; not a typed extension protocol | Server-side event history; external audit via CloudWatch/Datadog | Not defined | `AuditEvent.extensions: dict[str, BaseModel]`; `AuditExtensionProtocol` |
| Interrupt / human-in-the-loop TTL | DynamoDB TTL for checkpoint expiry; no native interrupt TTL | Signal-based; Activity heartbeat timeout serves as TTL | N/A | `InterruptRequest.expires_at` already stored; enforcement wired into `LocalRuntime` resume path |
| Memory scoping | Short-term (thread state) vs long-term (cross-thread store, vector DB) | No native memory model | Not defined | `MemoryConnector` Protocol with `thread`, `workflow`, `global` scopes |
| Policy fault isolation | No policy engine; exceptions in nodes propagate to the graph runner | Activity-level isolation via retry + timeout; exceptions are recorded events | N/A | Per-policy `asyncio.wait_for` + `except Exception`; failed policy = `PolicyDecision(allow=False)` |

---

## Complexity and GovernAI Primitive Dependencies

| Feature | Existing GovernAI Primitives Used | New Primitives Introduced | Zeroth Workaround to Retire |
|---------|----------------------------------|--------------------------|----------------------------|
| Transactional state persistence | `RunStore`, `RedisRunStore` | Atomic write helper, optional lock interface | N/A (new correctness guarantee) |
| Policy fault isolation | `PolicyEngine`, `PolicyDecision` | Per-policy timeout + exception wrapper | `policy/` guard wrappers in Zeroth |
| Policy capability model | `PolicyEngine`, `Tool.capabilities`, `Agent.capabilities` | `CapabilityGrant`, `CapabilityPolicy` | `policy/` capability checks in Zeroth |
| Contract versioning | `Tool`, `GovernedStepSpec` | `version` field, `ToolRegistry(name, version)` key, `contract_migrate` hook | `contracts/registry.py` in Zeroth |
| AgentSpec | `Agent` (all non-callable fields) | `AgentSpec(BaseModel)`, `Agent.from_spec()` | Ad-hoc YAML/JSON in Zeroth |
| ToolManifest | `Tool` (all non-callable fields) | `ToolManifest(BaseModel)`, `Tool.to_manifest()` | `execution_units/adapters.py` in Zeroth |
| Rich thread lifecycle | `RunStore`, `ThreadAwareRunStore`, `RunState` | `ThreadRecord`, `ThreadStatus` enum, `ThreadStore` | `runs/models.py` in Zeroth |
| Secrets-aware execution context | `ExecutionContext` (runtime context) | `SecretsProvider` Protocol, `SecretRef`, redaction pass in emitter | `secrets/` in Zeroth |
| Audit event enrichment | `AuditEvent`, `AuditEmitter` | `extensions` field, `AuditExtensionProtocol` | `audit/` enrichment in Zeroth |
| Interrupt TTL enforcement | `InterruptManager`, `InterruptRequest.expires_at`, `clear_expired` | Enforcement hook in `LocalRuntime` resume path, sweep API | N/A (correctness gap, not a workaround) |
| Memory connector protocol | `AuditEmitter`, `RunState.channels` | `MemoryConnector` Protocol, scope enum, memory audit event type | `memory/` in Zeroth |

---

## Sources

- LangGraph thread lifecycle and checkpoint persistence: [LangGraph Threads Docs](https://docs.langchain.com/langsmith/use-threads), [LangGraph DynamoDB persistence (AWS)](https://aws.amazon.com/blogs/database/build-durable-ai-agents-with-langgraph-and-amazon-dynamodb/)
- LangGraph thread statuses (idle/busy/interrupted/error): [LangGraph Issues — thread state](https://github.com/langchain-ai/langgraph/issues/6362)
- Temporal state atomicity and durability: [Temporal Workflows Docs](https://docs.temporal.io/workflows), [Temporal Workflow Execution](https://docs.temporal.io/workflow-execution)
- Oracle Open Agent Specification (AgentSpec): [Oracle Agent Spec GitHub](https://github.com/oracle/agent-spec), [Oracle Agent Spec Technical Report (arXiv)](https://arxiv.org/html/2510.04173v1)
- Redis distributed locking and WATCH/MULTI/EXEC: [Redis Distributed Locks Docs](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/), [Redis Transactions Docs](https://redis.io/docs/latest/develop/using-commands/transactions/)
- Secrets management and audit redaction for AI agents: [HashiCorp Vault AI Agent Identity](https://developer.hashicorp.com/validated-patterns/vault/ai-agent-identity-with-hashicorp-vault), [AI Agent Secrets Management Best Practices (Fast.io)](https://fast.io/resources/ai-agent-secrets-management/)
- Airflow secrets backends: [Mastering Apache Airflow Part 6 — Secrets Backends](https://softwarefrontier.substack.com/p/mastering-apache-airflow-part-6-secrets)
- Argo Workflows TTL strategy: [TTL Strategy — Adaptive Enforcement Lab](https://adaptive-enforcement-lab.com/developer-guide/argo-workflows/concurrency/ttl/)
- Structured audit logging: [Splunk Structured Audit Trail Logs](https://help.splunk.com/en/splunk-cloud-platform/administer/manage-users-and-security/10.1.2507/audit-activity-in-the-splunk-platform/about-structured-audit-trail-logs)
- Pydantic schema versioning patterns: [python-semver + Pydantic](https://python-semver.readthedocs.io/en/latest/advanced/combine-pydantic-and-semver.html)
- LangGraph memory architecture (short-term vs long-term): [LangGraph Memory Overview](https://docs.langchain.com/oss/python/langgraph/memory)
- CrewAI declarative agent definitions: [CrewAI Agents Docs](https://docs.crewai.com/en/concepts/agents)
- Martin Kleppmann on distributed locking: [How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)

---

*Feature research for: GovernAI v0.3.0 — governance depth*
*Researched: 2026-04-05*
