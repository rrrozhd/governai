---
phase: 03-runtime-depth
plan: "04"
subsystem: runtime/secrets
tags: [secrets, redaction, audit, capability, thread-store, local-runtime]
dependency_graph:
  requires: ["03-01", "03-02", "03-03"]
  provides: ["SEC-01", "SEC-02", "SEC-03", "THR-03", "D-08", "D-09", "D-10", "D-11"]
  affects: ["governai/runtime/local.py", "governai/runtime/context.py", "governai/runtime/secrets.py"]
tech_stack:
  added: []
  patterns:
    - "Protocol + No-Op Default for SecretsProvider/NullSecretsProvider"
    - "Decorator/wrapper pattern for RedactingAuditEmitter"
    - "model_dump_json/model_validate_json for full-event redaction (prevents partial-field leaks)"
    - "Per-runtime SecretRegistry with set accumulation (safe over-redaction)"
key_files:
  created:
    - governai/runtime/secrets.py
    - tests/test_secrets.py
  modified:
    - governai/runtime/context.py
    - governai/runtime/local.py
decisions:
  - "RedactingAuditEmitter uses model_dump_json() + model_validate_json() for whole-event redaction — guarantees extensions.data and all nested fields are covered (Pitfall 2 avoidance)"
  - "SecretRegistry scope is per-runtime (not per-run): safe over-redaction is preferred over regulatory violation from missed redaction"
  - "LocalRuntime only wraps audit_emitter with RedactingAuditEmitter when secrets_provider is explicitly provided — no-op default avoids performance cost when secrets unused"
  - "archive_thread() follows interrupt event pattern: store handles state, runtime emits audit event (D-08)"
metrics:
  duration: "5 minutes"
  completed: "2026-04-05"
  tasks: 2
  files: 4
---

# Phase 03 Plan 04: Secrets-Aware Runtime and LocalRuntime Wiring Summary

**One-liner:** Late-bound secrets resolution with full-event audit redaction pipeline wired into LocalRuntime alongside grants (CapabilityPolicy) and thread_store (InMemoryThreadStore) injection.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | SecretsProvider protocol, NullSecretsProvider, SecretRegistry, RedactingAuditEmitter, ExecutionContext.resolve_secret (TDD: RED then GREEN) | b484e2a | governai/runtime/secrets.py, governai/runtime/context.py |
| 2 | Wire grants, secrets_provider, thread_store into LocalRuntime; archive_thread with THREAD_ARCHIVED audit event | 06affce | governai/runtime/local.py, tests/test_secrets.py |

## What Was Built

### governai/runtime/secrets.py (new)

- `SecretsProvider`: `runtime_checkable` Protocol with `async resolve(key: str) -> str`
- `NullSecretsProvider`: default no-op that raises `KeyError("No SecretsProvider configured...")` — tools fail fast with a descriptive message
- `SecretRegistry`: accumulates resolved secret values via `register(value)`, applies `redact(text)` via string replacement; empty strings never registered
- `RedactingAuditEmitter`: wraps any `AuditEmitter`, applies redaction over `model_dump_json()` before round-tripping via `model_validate_json()` — covers payload, extensions.data, and all other fields

### governai/runtime/context.py (updated)

- `ExecutionContext.__init__` accepts `secrets_provider: SecretsProvider | None` and `secret_registry: SecretRegistry | None`
- New `async def resolve_secret(key: str) -> str`: delegates to provider, registers returned value in registry if present

### governai/runtime/local.py (updated)

- New `__init__` parameters: `grants`, `secrets_provider`, `thread_store`
- Grants wiring: `make_capability_policy(grants)` registered as `"capability_policy"` in `policy_engine` when grants provided
- Secrets wiring: `SecretRegistry()` always created; `RedactingAuditEmitter` wraps `audit_emitter` only when `secrets_provider` is non-None
- Thread store: `self.thread_store = thread_store or InMemoryThreadStore()`
- Both `ExecutionContext` construction sites (tool execution + agent execution) receive `secrets_provider` and `secret_registry`
- New `async def archive_thread(thread_id, *, run_id, workflow_name)`: calls `thread_store.archive()`, emits `EventType.THREAD_ARCHIVED` with `thread_id` and `run_ids` in payload

## Test Results

- `tests/test_secrets.py`: 16 tests (11 Task 1 + 5 Task 2) — all pass
- Full suite: 205 tests pass, 0 failures

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

**One minor adjustment:** The plan's `test_local_runtime_grants_wiring` test checked `runtime.policy_engine._policies`, but `PolicyEngine` uses `_global` (a list of tuples). The test was corrected to `[name for name, _ in runtime.policy_engine._global]` to match the actual implementation. This is a test correctness fix, not a plan deviation.

## Known Stubs

None — all implementations are fully wired with real data sources.

## Self-Check: PASSED

Files exist:
- FOUND: governai/runtime/secrets.py
- FOUND: governai/runtime/context.py (updated)
- FOUND: governai/runtime/local.py (updated)
- FOUND: tests/test_secrets.py

Commits exist:
- FOUND: 8734548 (RED tests)
- FOUND: b484e2a (Task 1 implementation)
- FOUND: 06affce (Task 2 wiring)
