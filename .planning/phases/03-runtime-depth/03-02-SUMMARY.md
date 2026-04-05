---
phase: 03-runtime-depth
plan: 02
subsystem: policies
tags: [capability, policy, pydantic, tdd]
dependency_graph:
  requires: [governai/models/policy.py, governai/policies/base.py, governai/policies/engine.py]
  provides: [governai/policies/capability.py]
  affects: [governai/policies/engine.py (consumer), LocalRuntime (future plan 04)]
tech_stack:
  added: []
  patterns: [PolicyFunc-compatible factory, Pydantic BaseModel with Literal scoping]
key_files:
  created:
    - governai/policies/capability.py
    - tests/test_capability_policy.py
  modified: []
decisions:
  - "CapabilityGrant defaults to scope='global' with target=None for ergonomic single-arg usage"
  - "make_capability_policy() is a closure capturing grants list — no class needed, stays lean"
  - "Deny reason format: 'Missing capability: X. Required: [X, Y]. Granted: [Y, Z].' — sorted for determinism"
metrics:
  duration: 3min
  completed: 2026-04-05
  tasks: 1
  files: 2
---

# Phase 03 Plan 02: CapabilityGrant Model and Policy Factory Summary

**One-liner:** CapabilityGrant Pydantic model with global/workflow/step scoping and make_capability_policy() factory returning a PolicyFunc-compatible deny-with-diagnostic function.

## What Was Built

`governai/policies/capability.py` provides:

1. **`CapabilityGrant`** — Pydantic BaseModel with three fields:
   - `capability: str` — the capability name (e.g., "net", "db", "fs")
   - `scope: GrantScope` — one of "global", "workflow", "step"; defaults to "global"
   - `target: str | None` — workflow name for scope="workflow", step name for scope="step"

2. **`make_capability_policy(grants: list[CapabilityGrant])`** — Factory returning a synchronous `PolicyFunc`-compatible callable that:
   - Allows immediately if `ctx.capabilities` is empty
   - Resolves the effective granted set by matching each grant's scope against the context
   - On missing capabilities: returns `PolicyDecision(allow=False, reason=...)` with diagnostic listing missing, required, and granted capabilities
   - On full coverage: returns `PolicyDecision(allow=True)`

## Tests

15 tests in `tests/test_capability_policy.py` covering:
- Global, workflow-scoped, and step-scoped grant matching
- Correct rejection when workflow/step target doesn't match context
- No-capabilities-required always passes
- Deny diagnostic message format verification
- Partial grant with mixed missing/granted
- Multiple grants combining
- Model default validation (scope="global", target=None)
- PolicyEngine integration (raises PolicyDeniedError on missing capability)
- PolicyEngine integration (passes when capability granted)

All 15 tests pass. Full suite (98 tests) passes without regressions. The one pre-existing failure (`test_remote_execution.py::test_http_sandbox_tool_execution_end_to_end`) is unrelated — it requires the optional `governai[sandbox]` FastAPI extra.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 883b41d | test | Add failing tests for CapabilityGrant and make_capability_policy (RED) |
| 8458d1b | feat | Implement CapabilityGrant model and make_capability_policy factory (GREEN) |

## Deviations from Plan

None — plan executed exactly as written. Implementation matches the code skeleton provided in the plan spec verbatim.

## Known Stubs

None.

## Self-Check: PASSED

- `governai/policies/capability.py` exists and contains `class CapabilityGrant(BaseModel):`, `scope: GrantScope = "global"`, `target: str | None = None`, `def make_capability_policy`, `Missing capability:`, `Required: [`, `Granted: [`
- `tests/test_capability_policy.py` exists with 15 test functions (>= 10 required)
- All capability tests pass
- No regressions in full suite
