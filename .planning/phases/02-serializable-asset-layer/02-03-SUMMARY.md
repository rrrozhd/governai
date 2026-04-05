---
phase: 02-serializable-asset-layer
plan: 03
subsystem: runtime
tags: [redis, watch-multi-exec, optimistic-locking, epoch-cas, pydantic]

# Dependency graph
requires:
  - phase: 01-foundations
    provides: RunState model with epoch field, InMemoryRunStore, RedisRunStore
provides:
  - StateConcurrencyError exception for optimistic lock conflicts
  - Atomic RedisRunStore.put() with WATCH/MULTI/EXEC and WatchError retry
  - Epoch-based CAS on InMemoryRunStore.put() with auto-increment
  - _validate_state() for status-field consistency checks
  - v0.2.2 RunState JSON fixture for backward compatibility
affects: [03-runtime-depth, 04-audit-memory]

# Tech tracking
tech-stack:
  added: [redis.exceptions.WatchError]
  patterns: [WATCH/MULTI/EXEC atomic boundary, epoch-based CAS, state validation before persistence]

key-files:
  created:
    - tests/test_atomic_run_store.py
    - tests/fixtures/run_state_v022.json
  modified:
    - governai/runtime/run_store.py
    - governai/__init__.py
    - governai/runtime/local.py
    - tests/test_run_store.py
    - tests/test_interrupt_persistence.py

key-decisions:
  - "Epoch comparison uses strict > (not >=) so caller can write with current epoch and auto-increment proceeds"
  - "Runtime no longer manually sets state.epoch from interrupt manager; put() auto-increments epoch independently"
  - "Interrupt epoch synced after state persistence to keep resume epoch consistent"

patterns-established:
  - "Atomic persistence: All run state writes go through WATCH/MULTI/EXEC on Redis, epoch CAS on in-memory"
  - "State validation: _validate_state() called before any persistence operation"
  - "TransactionalFakeRedis: Test double for Redis pipeline with watch/multi/execute support"

requirements-completed: [PERS-01, PERS-02, PERS-03]

# Metrics
duration: 8min
completed: 2026-04-05
---

# Phase 2 Plan 3: Atomic Run Store Summary

**WATCH/MULTI/EXEC atomic writes on RedisRunStore with epoch-based CAS, state validation, and v0.2.2 backward compatibility**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-05T14:21:02Z
- **Completed:** 2026-04-05T14:28:32Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 7

## Accomplishments
- RedisRunStore.put() uses WATCH/MULTI/EXEC atomic boundary covering state write + checkpoint, with 3 retries and exponential backoff on WatchError
- InMemoryRunStore.put() rejects stale epoch writes and auto-increments epoch on successful writes
- Both stores validate state consistency (WAITING_INTERRUPT requires pending_interrupt_id, WAITING_APPROVAL requires pending_approval)
- StateConcurrencyError exported at top-level for consumer use
- v0.2.2 RunState JSON fixture deserializes cleanly (unknown fields silently ignored)
- 12 new test cases covering all atomic persistence behaviors

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Add failing tests for atomic run store** - `e265248` (test)
2. **Task 1 GREEN: Implement atomic writes and epoch CAS** - `48c34b7` (feat)

_TDD task: RED commit has failing tests, GREEN commit makes them pass._

## Files Created/Modified
- `governai/runtime/run_store.py` - StateConcurrencyError, _validate_state, atomic put() for both stores
- `governai/__init__.py` - Export StateConcurrencyError
- `governai/runtime/local.py` - Fix runtime epoch management to use put() auto-increment
- `tests/test_atomic_run_store.py` - 12 tests: concurrency error, validation, epoch CAS, atomic writes, retry, fixture
- `tests/fixtures/run_state_v022.json` - v0.2.2 RunState fixture with unknown future field
- `tests/test_run_store.py` - Added pipeline support to FakeRedis
- `tests/test_interrupt_persistence.py` - Added pipeline support to AsyncFakeRedis

## Decisions Made
- Used strict `>` comparison for epoch staleness (not `>=`) so that a write with the current epoch succeeds and auto-increments, while only truly older epochs are rejected
- Removed manual `state.epoch = await self._interrupt_bump_epoch()` from runtime resume paths since put() now manages epoch auto-increment internally
- Added interrupt epoch sync after state persistence to keep interrupt resume epoch consistent with final state epoch
- WatchError import uses try/except with fallback class for environments without redis package

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added pipeline support to existing FakeRedis test doubles**
- **Found during:** Task 1 GREEN (implementation)
- **Issue:** Existing FakeRedis in test_run_store.py and AsyncFakeRedis in test_interrupt_persistence.py lacked pipeline() method, causing AttributeError when RedisRunStore.put() uses pipeline
- **Fix:** Added _FakePipeline and _AsyncFakePipeline classes with watch/multi/execute support to both test files
- **Files modified:** tests/test_run_store.py, tests/test_interrupt_persistence.py
- **Verification:** All existing tests pass (127/127)
- **Committed in:** 48c34b7

**2. [Rule 1 - Bug] Fixed dual epoch tracking conflict between interrupt manager and run store**
- **Found during:** Task 1 GREEN (implementation)
- **Issue:** Runtime was setting state.epoch from interrupt manager's epoch counter, but put() now auto-increments epoch independently, causing StateConcurrencyError on resume (store epoch=4, write epoch=2)
- **Fix:** Changed runtime to not manually set state.epoch from interrupt manager; let put() manage it. Added interrupt epoch sync after persist to keep resume consistent.
- **Files modified:** governai/runtime/local.py
- **Verification:** test_command_interrupts and test_interrupt_persistence pass
- **Committed in:** 48c34b7

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both auto-fixes necessary for correctness. FakeRedis pipeline support is required for compatibility with the new atomic put(). Epoch tracking fix resolves a real conflict between two independent epoch systems.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all functionality is fully wired.

## Next Phase Readiness
- Atomic persistence foundation is complete for all run store operations
- TransactionalFakeRedis pattern available for future tests needing pipeline simulation
- State validation can be extended with additional consistency rules in future plans

---
*Phase: 02-serializable-asset-layer*
*Completed: 2026-04-05*
