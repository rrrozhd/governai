---
phase: 03-runtime-depth
plan: 03
subsystem: runtime
tags: [thread-lifecycle, state-machine, persistence, pydantic, async]
dependency_graph:
  requires: []
  provides: [ThreadStatus, ThreadRecord, ThreadStore, InMemoryThreadStore, ThreadTransitionError]
  affects: []
tech_stack:
  added: []
  patterns: [ABC-with-async-abstractmethods, model_copy-deep-True, ALLOWED_THREAD_TRANSITIONS-state-machine, ThreadTransitionError-ValueError]
key_files:
  created:
    - governai/runtime/thread_store.py
    - tests/test_thread_store.py
  modified: []
decisions:
  - archive() delegates to transition(ARCHIVED) -- no separate deletion path, audit trail preserved
  - ALLOWED_THREAD_TRANSITIONS dict provides O(1) transition validation per D-06
  - model_copy(deep=True) on all returned records for defensive copy safety
  - ThreadTransitionError extends ValueError matching codebase error hierarchy conventions
metrics:
  duration: 5min
  completed_date: "2026-04-05"
  tasks_completed: 1
  files_created: 2
  files_modified: 0
requirements: [THR-01, THR-02, THR-03]
---

# Phase 3 Plan 3: ThreadStore — Thread Lifecycle State Machine Summary

**One-liner:** ThreadStatus enum + ThreadRecord model + ThreadStore ABC + InMemoryThreadStore with ALLOWED_THREAD_TRANSITIONS dict enforcing the 5-state lifecycle (created -> active -> interrupted/idle -> archived).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | ThreadStatus, ThreadRecord, ThreadStore ABC, InMemoryThreadStore | bfb60b6 | governai/runtime/thread_store.py, tests/test_thread_store.py |

## What Was Built

### governai/runtime/thread_store.py

A new standalone module implementing the full thread lifecycle model per D-05 and D-06:

- **ThreadStatus(str, Enum):** 5 states — `created`, `active`, `interrupted`, `idle`, `archived` (lowercase string values matching codebase convention from RunStatus)
- **ALLOWED_THREAD_TRANSITIONS:** Dict-based state machine restricting: created->active, active->idle|interrupted, interrupted->active, idle->active|archived, archived->nothing (terminal)
- **ThreadTransitionError(ValueError):** Raised on invalid transitions with descriptive message including thread_id, from-state, to-state
- **ThreadRecord(BaseModel):** thread_id, status, run_ids, created_at, updated_at (datetime with timezone), metadata(dict); all timestamps use _utcnow() helper
- **ThreadStore(ABC):** async-first ABC with create/get/transition/add_run_id/archive abstract methods — follows InterruptStore structural twin pattern per D-05
- **InMemoryThreadStore(ThreadStore):** Dict-backed implementation; all returned records use model_copy(deep=True) for defensive copying; archive() delegates to transition(ARCHIVED)

### tests/test_thread_store.py

21 tests covering:
- ThreadStatus enum values (exactly 5, correct string values)
- ThreadRecord defaults and model_dump_json/model_validate_json roundtrip
- create/get/duplicate detection/not-found behavior
- All valid transitions: created->active, active->idle, active->interrupted, interrupted->active, idle->active (re-activation), idle->archived
- Invalid transitions: created->archived raises ThreadTransitionError, archived->active raises ThreadTransitionError (terminal)
- updated_at timestamp changes after transition
- KeyError on transition of unknown thread_id
- add_run_id single and multiple run associations
- archive() transitions to ARCHIVED and record still retrievable via get()
- Deep copy isolation: mutating returned record does not affect store state

## Decisions Made

1. **archive() as transition:** archive() simply calls transition(thread_id, ARCHIVED). No deletion path exists — this preserves the audit trail (THR-03). Archived records remain retrievable via get().

2. **ALLOWED_THREAD_TRANSITIONS dict:** Per D-06, state machine is enforced at the dict level for O(1) lookup. ARCHIVED maps to an empty set() making it terminal without special-casing.

3. **model_copy(deep=True) everywhere:** create(), get(), transition(), add_run_id(), archive() all return deep copies. This prevents callers from mutating store state through returned objects.

4. **ThreadTransitionError extends ValueError:** Consistent with codebase style (StateConcurrencyError extends RuntimeError, InterruptExpiredError extends RuntimeError). ValueError is appropriate for invalid state arguments.

## Deviations from Plan

None — plan executed exactly as written. The implementation in the plan's `<action>` block was used verbatim, including file structure, all type annotations, and docstrings.

## Verification

- `python3.13 -m pytest tests/test_thread_store.py -x -v` — 21/21 passed
- `python3.13 -m pytest tests/ -x` — 20 pre-existing failures unchanged, 0 new failures introduced
- ThreadRecord survives full lifecycle: created -> active -> interrupted -> active -> idle -> archived
- Archived thread retrievable via get() with status=ARCHIVED
- Pre-existing test failures confirmed pre-existing via git stash baseline check (20 failures before and after)

## Known Stubs

None.

## Self-Check: PASSED

- governai/runtime/thread_store.py exists: FOUND
- tests/test_thread_store.py exists: FOUND
- commit bfb60b6 exists: FOUND
- `class ThreadStatus(str, Enum)` in thread_store.py: FOUND
- `ALLOWED_THREAD_TRANSITIONS` in thread_store.py: FOUND
- `class ThreadTransitionError(ValueError)` in thread_store.py: FOUND
- `class ThreadRecord(BaseModel)` in thread_store.py: FOUND
- `class ThreadStore(ABC)` in thread_store.py: FOUND
- `class InMemoryThreadStore(ThreadStore)` in thread_store.py: FOUND
- `model_copy(deep=True)` in thread_store.py: FOUND
- 21 test functions in tests/test_thread_store.py: FOUND
