# Phase 3: Runtime Depth - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

The policy engine enforces declared capability grants before execution, thread lifecycle is tracked and auditable through all state transitions including archival, secrets are resolved at call time and never appear in persisted audit events, and audit events carry typed extension metadata from consumers.

</domain>

<decisions>
## Implementation Decisions

### Capability Enforcement
- **D-01:** Capability check is a built-in policy (CapabilityPolicy) that runs inside PolicyEngine.evaluate() like any other policy. Follows Phase 1 deny pattern — PolicyDecision(allow=False, reason='...').
- **D-02:** Three-tier grant scoping: global, workflow-scoped, and step-scoped grants via CapabilityGrant(capability, scope=global|workflow|step, target=optional). Matches CAP-02.
- **D-03:** Grants provided via constructor injection — LocalRuntime receives grants: list[CapabilityGrant] at init. The built-in CapabilityPolicy reads them. Zeroth populates grants from its own RBAC layer.
- **D-04:** Full diagnostic deny — PolicyDecision lists both required and granted capabilities. E.g., "Missing capability: X. Required: [X, Y]. Granted: [Y, Z]." Matches CAP-03.

### Thread Lifecycle
- **D-05:** ThreadStore is a new standalone ABC (like RunStore, InterruptStore). Separate concerns — RunStore manages run state, ThreadStore manages thread lifecycle. Both get Redis and InMemory implementations.
- **D-06:** Linear transitions with interrupt cycle: created→active→idle→archived, plus active→interrupted→active for interrupt cycles. Invalid transitions raise error. Matches THR-01 states.
- **D-07:** ThreadRecord.run_ids: list[str] tracks which runs have used the thread (multi-run association). Updated when a run starts on this thread.
- **D-08:** Thread archival emits a THREAD_ARCHIVED audit event. Audit stream captures lifecycle transitions. Consistent with interrupt event pattern. Matches THR-03 audit trail requirement.

### Secrets Redaction
- **D-09:** SecretsProvider is a typing.Protocol with async resolve(key: str) -> str. Follows "Protocol + No-Op Default" pattern — a NullSecretsProvider that raises on any resolve() ships as default. Matches SEC-01.
- **D-10:** Redaction happens at emitter level (pre-persist). AuditEmitter wraps emit() with a redaction pass — before persisting, scans event payload for known secret values and replaces with [REDACTED].
- **D-11:** SecretRegistry tracks resolved values. When SecretsProvider.resolve() is called, the resolved value is registered with a SecretRegistry. The emitter's redaction pass scans for all registered values.

### Audit Extensions
- **D-12:** AuditEvent gains extensions: list[AuditExtension] field. AuditExtension is a BaseModel with type_key: str + data: dict. Defaults to []. v0.2.2 events deserialize to extensions=[] without error.
- **D-13:** Extensions validated at emit time — AuditExtension is a Pydantic model, validated on construction. Bad data fails immediately. Matches AUD-02.
- **D-14:** Consumer registration via BaseModel subclass pattern. Consumers define AuditExtension subclasses with a fixed type_key discriminator. E.g., ZerothTraceExtension(type_key='zeroth.trace', data={...}). No central registry needed.
- **D-15:** Emitters serialize extensions transparently via model_dump() on the full AuditEvent. Pydantic handles serialization/deserialization. Zero extra code in emitter implementations. Matches AUD-03.

### Claude's Discretion
- ThreadRecord field design beyond status, thread_id, run_ids (created_at, updated_at, metadata, etc.)
- SecretRegistry scope (per-run vs per-runtime) and thread-safety approach
- CapabilityPolicy registration mechanism (auto-registered if grants provided, or explicit)
- Thread state transition validation implementation (enum-based allowed map vs explicit checks)
- Exact EventType enum values for new thread lifecycle events
- NullSecretsProvider error message when resolve() is called without a real provider

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Policy & Capability System
- `governai/policies/engine.py` — PolicyEngine.evaluate() where CapabilityPolicy will run
- `governai/policies/base.py` — PolicyFunc type and _run_policy_isolated wrapper (Phase 1 fault isolation)
- `governai/models/policy.py` — PolicyContext (already has capabilities: list[str]) and PolicyDecision
- `governai/tools/base.py` — Tool class with capabilities field (source of required capabilities)
- `governai/tools/manifest.py` — ToolManifest with capabilities (for pre-flight checks)

### Runtime & Execution Context
- `governai/runtime/local.py` — LocalRuntime (receives grants, wires secrets provider)
- `governai/runtime/context.py` — ExecutionContext (needs SecretsProvider injection)

### Audit System
- `governai/models/audit.py` — AuditEvent model (gains extensions field)
- `governai/audit/emitter.py` — AuditEmitter ABC and emit_event() helper (redaction wraps here)
- `governai/audit/redis.py` — RedisAuditEmitter (must handle extensions transparently)
- `governai/audit/memory.py` — InMemoryAuditEmitter (must handle extensions transparently)
- `governai/models/common.py` — EventType enum (needs new thread lifecycle + capability event types)

### Store Interfaces
- `governai/runtime/run_store.py` — RunStore ABC pattern (ThreadStore follows same pattern)
- `governai/runtime/interrupts.py` — InterruptStore ABC (async-first pattern reference)

### Tests
- `tests/test_policy_checks.py` — Existing policy tests (extend for capability checks)
- `tests/test_interrupt_persistence.py` — Store test patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PolicyEngine` with global + workflow-scoped policy registration — CapabilityPolicy plugs in here
- `PolicyContext.capabilities: list[str]` — already exists, carries required capabilities from tool
- `Tool.capabilities: list[str]` — source of required capabilities, flows into PolicyContext
- `ToolManifest.capabilities` — enables Studio pre-flight capability checks without live tools
- `AuditEmitter` ABC with emit() — redaction wraps this method
- `emit_event()` helper — may need extensions parameter addition
- `InterruptStore` ABC pattern — ThreadStore follows identical async ABC + InMemory + Redis impl pattern

### Established Patterns
- ABC for store interfaces (RunStore, InterruptStore) — ThreadStore follows
- Pydantic BaseModel for all data models — ThreadRecord, CapabilityGrant, AuditExtension follow
- typing.Protocol for injectable dependencies — SecretsProvider follows
- async-first stores (Phase 1 migration) — ThreadStore is async from day one
- Version defaults to '0.0.0', schema fingerprint blake2b 16-byte — conventions carry forward
- PolicyDecision(allow=False, reason='...') — capability denials follow this exact pattern

### Integration Points
- `LocalRuntime.__init__()` — add grants parameter, secrets_provider parameter, thread_store parameter
- `PolicyEngine.evaluate()` — CapabilityPolicy is registered as a built-in policy
- `ExecutionContext.__init__()` — add secrets_provider parameter
- `AuditEvent` model — add extensions field with backward-compatible default
- `EventType` enum — add THREAD_CREATED, THREAD_ARCHIVED, CAPABILITY_DENIED, etc.
- `emit_event()` — add extensions parameter

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-runtime-depth*
*Context gathered: 2026-04-05*
