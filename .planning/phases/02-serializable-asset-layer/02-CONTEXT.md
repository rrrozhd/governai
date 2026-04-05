# Phase 2: Serializable Asset Layer - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Agent and tool definitions become serializable Pydantic models (AgentSpec, ToolManifest) that Zeroth Studio can store, transmit, and reconstruct. All state writes become atomic via WATCH/MULTI/EXEC so a crash between write and cache never leaves a run inconsistent.

</domain>

<decisions>
## Implementation Decisions

### AgentSpec Shape
- **D-01:** AgentSpec stores input/output models as JSON Schema dicts (via `model_json_schema()`). Fully serializable. Model reconstruction at `from_spec()` time via a ModelRegistry.
- **D-02:** Each model reference stored as `{name: str, schema: dict}` pair. The name enables registry-based reconstruction; the schema enables Studio display/validation without loading Python classes.
- **D-03:** AgentSpec carries `version` (SemVer, default `'0.0.0'`) and `schema_fingerprint` (blake2b, same pattern as Tool from Phase 1). Enables future AgentRegistry keying by `(name, version)`.
- **D-04:** `allowed_tools` stays as `list[str]` of tool names. Tool resolution happens at `from_spec()` time using ToolRegistry. No version pinning on tool references.
- **D-05:** `Agent.from_spec(spec, handler, registry=None)` takes the callable handler as required arg and an optional ModelRegistry for resolving input/output model classes by name. Raises if models are needed but registry is None or name not found.
- **D-06:** ModelRegistry protocol: `resolve(name: str) -> type[BaseModel]`. Simple name-based lookup. No versioning on model resolution.
- **D-07:** `Agent.to_spec()` is a method on Agent (mirrors `Tool.to_manifest()` pattern). Extraction logic stays close to the source.

### ToolManifest Design
- **D-08:** ToolManifest carries all Tool data fields: name, version, description, input/output schemas (as JSON Schema dicts), schema_fingerprint, capabilities, side_effect, timeout_seconds, requires_approval, tags, executor_type, execution_placement, remote_name. Complete description for Studio rendering and policy evaluation without the callable.
- **D-09:** ToolManifest is read-only metadata. No `to_tool()` reconstruction path. Tool instances are always created from Python code with actual callables.
- **D-10:** ToolManifest is usable for capability checks without a live Tool. Policy engine can evaluate capabilities, placement, and approval requirements using just the manifest. Enables Studio pre-flight checks before tools are loaded.

### Atomic Persistence
- **D-11:** WATCH/MULTI/EXEC transaction boundary includes both the state payload write AND the checkpoint index entry. A crash mid-write rolls back both.
- **D-12:** Optimistic lock conflict triggers retry with exponential backoff (up to 3 retries). Raises typed `StateConcurrencyError` if retries exhausted.
- **D-13:** PERS-03 validation (handoff targets, command state updates, transitions) lives in the store layer. RedisRunStore.put() validates before writing. Store is the gatekeeper — invalid state never reaches Redis.
- **D-14:** InMemoryRunStore gets epoch-based compare-and-swap for test parity with Redis atomic semantics. Tests exercise the same concurrency contract.

### Backward Compatibility
- **D-15:** AgentSpec and ToolManifest are new standalone models. GovernedFlowSpec/GovernedStepSpec gain no new required fields. Zeroth's existing flow construction continues unchanged. Zeroth adopts specs at its own pace.
- **D-16:** v0.2.2 RunState deserialization verified via committed JSON fixture test. A real v0.2.2 RunState JSON blob is committed as a test fixture; `model_validate_json()` must succeed with no ValidationError.

### Claude's Discretion
- Unknown field handling on RunState validation (ignore vs forbid) — decide based on Zeroth's usage pattern and forward-compatibility needs
- Exact retry backoff timing for optimistic lock conflicts
- StateConcurrencyError exception hierarchy placement
- ModelRegistry default implementation (if any ships with GovernAI vs left to consumers)
- Internal structure of the WATCH/MULTI/EXEC pipeline (key patterns, TTL handling within transaction)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Agent System
- `governai/agents/base.py` — Agent class definition (source for AgentSpec field extraction)
- `governai/agents/registry.py` — AgentRegistry (simple name-based keying, no versioning yet)

### Tool System
- `governai/tools/base.py` — Tool class with version field and schema fingerprint (Phase 1)
- `governai/tools/registry.py` — ToolRegistry with (name, version) keying (Phase 1)

### Persistence
- `governai/runtime/run_store.py` — RedisRunStore (current non-atomic writes), InMemoryRunStore, RunStore ABC
- `governai/models/run_state.py` — RunState model (Pydantic v2, all serialization entry points)

### Spec Layer
- `governai/app/spec.py` — GovernedFlowSpec, GovernedStepSpec (must not gain new required fields)

### Models
- `governai/models/common.py` — RunStatus, EventType enums; JSONValue type
- `governai/models/approval.py` — ApprovalRequest, ApprovalDecision (serialization patterns)

### Tests
- `tests/test_policy_checks.py` — Existing policy tests
- `tests/test_interrupt_persistence.py` — Existing persistence tests (pattern reference)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Tool.to_manifest()` pattern — already exists from Phase 1 for version/fingerprint extraction; ToolManifest extends this
- `ToolRegistry` versioned keying `(name, version)` — pattern to follow for AgentSpec fingerprinting
- `RunState.model_dump_json()` / `model_validate_json()` — established serialization pattern
- `model_json_schema()` — already used for schema fingerprinting in Phase 1; reuse for AgentSpec I/O schemas
- `state.model_copy(deep=True)` — isolation pattern in stores

### Established Patterns
- Pydantic BaseModel for all data models — AgentSpec and ToolManifest follow this
- ABC for store interfaces — RunStore ABC gets atomic write contract
- `blocking_io` flag removed in Phase 1 — all stores are async-first
- Version defaults to `'0.0.0'` — Phase 1 convention carries forward
- Schema fingerprint: blake2b 16-byte digest (32-char hex) — Phase 1 convention carries forward

### Integration Points
- `Agent.__init__()` — add `to_spec()` method
- `Agent.from_spec()` — new classmethod factory
- `Tool.to_manifest()` — may already exist partially from Phase 1 fingerprint work; extend to full ToolManifest
- `RedisRunStore.put()` / `write_checkpoint()` — refactor to WATCH/MULTI/EXEC
- `InMemoryRunStore.put()` — add epoch-based CAS
- Policy engine — extend to accept ToolManifest for capability checks (Phase 3 depends on this)

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

*Phase: 02-serializable-asset-layer*
*Context gathered: 2026-04-05*
