# Phase 1: Foundations - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Policy engine crash safety and fault isolation, interrupt TTL enforcement with async store migration, and contract versioning primitives. These are the foundation layers that Phases 2-4 build upon.

</domain>

<decisions>
## Implementation Decisions

### Policy Fault Isolation
- **D-01:** Fail-closed, short-circuit — a crashing or timed-out policy produces a deny decision and remaining policies are skipped. The run continues (not terminated) with the deny result.
- **D-02:** Per-policy timeout only — each policy declares its own timeout. No timeout declared means no timeout enforced. No global fallback default. Matches POL-02 and avoids starving legitimate slow policies.
- **D-03:** Diagnostics via PolicyDecision.reason — timeout and crash both produce `PolicyDecision(allow=False, reason='...')` with a descriptive message (e.g., "Policy X timed out after 5s", "Policy X raised ValueError: ..."). No new exception types for policy failures — the engine catches internally and converts to deny.

### Interrupt Store Migration
- **D-04:** InterruptStore ABC becomes fully async — all methods become async. InMemoryInterruptStore trivially awaits. RedisInterruptStore migrates to redis.asyncio. This is technically a breaking change to the ABC but aligns with the async-first principle.
- **D-05:** Sweep API lives on InterruptStore — `sweep_expired()` is a store-level method per INT-02. Global scope (not per-run) — cleans all expired interrupts across all runs. Suitable for background maintenance callers.

### Contract Version Model
- **D-06:** ToolRegistry keys on `(name, version)` tuple — `get('tool_x', '1.0.0')` returns exact version. No "latest" alias — callers must specify version. Matches CONT-02.
- **D-07:** Version field is optional, defaults to `'0.0.0'` — existing code that doesn't set a version still works. Additive change, no breakage to existing Tool or GovernedStepSpec usage.
- **D-08:** Schema fingerprint (blake2b on `model_json_schema()`) computed on registration — stored on the tool/manifest. Consumers compare fingerprints to detect schema drift between versions. No runtime cost per tool call.

### Error Typing Strategy
- **D-09:** InterruptExpiredError is a new exception class under a GovernAI base (or new InterruptError base). Replaces current ValueError on expired interrupt resolution with typed, catchable error.
- **D-10:** InterruptExpiredError carries the full expired InterruptRequest — callers can inspect run_id, step_name, created_at, expires_at for diagnostics and audit.
- **D-11:** Policy failures do NOT produce new exception types — they stay within PolicyDecision deny flow (see D-03). Only interrupts get new typed errors.

### Claude's Discretion
- Exception hierarchy design (whether InterruptError is a new base or reuses existing GovernAI exceptions)
- Exact blake2b digest size for schema fingerprinting
- Internal implementation of asyncio.wait_for wrapping in policy engine
- Redis key patterns for global sweep_expired

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Policy Engine
- `governai/policies/engine.py` — Current PolicyEngine.evaluate() implementation (no fault isolation)
- `governai/policies/base.py` — PolicyFunc type and run_policy() wrapper
- `governai/models/policy.py` — PolicyContext and PolicyDecision models

### Interrupt System
- `governai/runtime/interrupts.py` — InterruptStore ABC, InMemoryInterruptStore, RedisInterruptStore, InterruptManager
- `governai/workflows/exceptions.py` — Existing exception hierarchy (for InterruptExpiredError placement)

### Contract Versioning
- `governai/tools/base.py` — Tool class (needs version field)
- `governai/tools/registry.py` — ToolRegistry (needs (name, version) keying)
- `governai/app/spec.py` — GovernedStepSpec (needs version field)

### Test References
- `tests/test_policy_checks.py` — Existing policy tests
- `tests/test_interrupt_persistence.py` — Existing interrupt persistence tests
- `tests/test_interrupt_manager.py` — Existing interrupt manager tests

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PolicyEngine` class with global + workflow-scoped policy registration — extend with fault isolation
- `run_policy()` helper — wrap with try/except and asyncio.wait_for for timeout
- `InterruptManager` — already has TTL fields, epoch guards, and clear_expired() per-run
- `InterruptRequest` dataclass — already has `expires_at` and `status` fields

### Established Patterns
- ABC for store interfaces (InterruptStore) — follow same pattern for async migration
- Pydantic BaseModel for data models (PolicyContext, PolicyDecision) — use for any new models
- `blocking_io` flag on stores — may need rethinking with async migration

### Integration Points
- `PolicyEngine.evaluate()` is called from `governai/runtime/local.py` — fault isolation changes here
- `InterruptManager.resolve()` currently raises ValueError — replace with InterruptExpiredError
- `ToolRegistry.register()` and `get()` — signature changes for (name, version) keying
- `Tool.__init__()` — add optional version parameter

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

*Phase: 01-foundations*
*Context gathered: 2026-04-05*
