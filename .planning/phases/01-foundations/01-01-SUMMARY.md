---
phase: 01-foundations
plan: 01
subsystem: policies
tags: [asyncio, fault-isolation, timeout, policy-engine]

# Dependency graph
requires: []
provides:
  - "_run_policy_isolated helper with try/except + asyncio.wait_for"
  - "Fault-isolated policy evaluation loop in local.py"
  - "Per-policy timeout via __policy_timeout__ attribute"
affects: [01-foundations-02, 02-assets]

# Tech tracking
tech-stack:
  added: []
  patterns: ["asyncio.wait_for for per-policy timeout enforcement", "Exception -> PolicyDecision(allow=False) fault isolation pattern"]

key-files:
  created: []
  modified:
    - governai/policies/base.py
    - governai/runtime/local.py
    - tests/test_policy_checks.py

key-decisions:
  - "Catch Exception (not BaseException) to let CancelledError propagate per Python 3.12 behavior"
  - "No global default timeout -- only policies with __policy_timeout__ get timeout enforcement"
  - "No new exception types for policy failures -- reuse PolicyDecision(allow=False) with diagnostic reason"

patterns-established:
  - "Fault isolation pattern: wrap policy execution in try/except, convert failures to deny decisions with diagnostic reasons"
  - "__policy_timeout__ attribute convention for per-policy timeout declaration"

requirements-completed: [POL-01, POL-02, POL-03]

# Metrics
duration: 2min
completed: 2026-04-05
---

# Phase 01 Plan 01: Policy Fault Isolation Summary

**Crash-safe policy engine with per-policy timeout via asyncio.wait_for and diagnostic deny decisions**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-05T11:59:18Z
- **Completed:** 2026-04-05T12:01:18Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Policy exceptions now produce deny decisions with diagnostic reasons instead of terminating the run
- Per-policy timeout enforcement via `__policy_timeout__` attribute and `asyncio.wait_for`
- Short-circuit behavior preserved: first deny skips remaining policies
- 4 new tests covering crash isolation, timeout deny, normal operation, and short-circuit behavior

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing tests for policy fault isolation** - `f20241d` (test)
2. **Task 2: Implement policy fault isolation (GREEN + wire)** - `4f02747` (feat)

## Files Created/Modified
- `governai/policies/base.py` - Added `_run_policy_isolated()` with crash/timeout isolation
- `governai/runtime/local.py` - Wired `_run_policy_isolated` into `_evaluate_policies` with `__policy_timeout__` lookup
- `tests/test_policy_checks.py` - 4 new fault isolation tests (crash deny, timeout deny, no-timeout normal, short-circuit)

## Decisions Made
- Catch `Exception` (not `BaseException`) to let `CancelledError` propagate safely per Python 3.12 semantics
- No global default timeout -- only policies declaring `__policy_timeout__` get timeout enforcement (per D-02)
- No new exception types for policy failures -- reuse `PolicyDecision(allow=False)` with diagnostic reason string (per D-11)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Policy fault isolation complete and tested
- `_run_policy_isolated` is available for import by other modules
- Ready for policy capability model work in future plans

## Self-Check: PASSED

All files exist, all commits verified.

---
*Phase: 01-foundations*
*Completed: 2026-04-05*
