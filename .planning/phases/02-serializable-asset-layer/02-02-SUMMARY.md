---
phase: 02-serializable-asset-layer
plan: 02
subsystem: tools
tags: [pydantic, serialization, manifest, blake2b, fingerprint]

requires:
  - phase: 01-foundations
    provides: "Tool base class with version and schema_fingerprint fields"
provides:
  - "ToolManifest Pydantic model for serializable tool descriptors"
  - "Tool.to_manifest() extraction method with inline fingerprint computation"
  - "Top-level ToolManifest export from governai package"
affects: [03-runtime-depth, agent-spec, studio-integration]

tech-stack:
  added: []
  patterns: ["lazy-import for circular dependency avoidance (manifest in to_manifest)", "inline blake2b fingerprint when tool unregistered"]

key-files:
  created:
    - governai/tools/manifest.py
    - tests/test_tool_manifest.py
  modified:
    - governai/tools/base.py
    - governai/__init__.py

key-decisions:
  - "Added version and schema_fingerprint to Tool.__init__ in this branch (Phase 1 dependency not yet merged to main)"
  - "Used lazy import in to_manifest() to avoid circular import between base.py and manifest.py"
  - "ToolManifest imports ExecutionPlacement from base.py (single source of truth for the Literal type)"

patterns-established:
  - "Manifest pattern: read-only Pydantic descriptor extracted from runtime object, no reconstruction path"
  - "Inline fingerprint: compute blake2b if schema_fingerprint is None, reuse if already set"

requirements-completed: [MFST-01, MFST-02, MFST-03]

duration: 3min
completed: 2026-04-05
---

# Phase 02 Plan 02: ToolManifest Summary

**ToolManifest Pydantic model with all Tool data fields, Tool.to_manifest() extraction with inline blake2b fingerprint, JSON-serializable with no reconstruction path (D-09)**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-05T14:21:01Z
- **Completed:** 2026-04-05T14:23:45Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 4

## Accomplishments
- Created ToolManifest Pydantic BaseModel carrying all Tool metadata fields except callable
- Added Tool.to_manifest() that extracts ToolManifest with inline blake2b fingerprint computation for unregistered tools
- Exported ToolManifest from top-level governai package
- 9 tests covering data fields, JSON round-trip, fingerprint computation, no-reconstruction constraint, and capability checks
- Full test suite (104 tests) passes with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests for ToolManifest** - `117c89f` (test)
2. **Task 1 GREEN: Implement ToolManifest and to_manifest()** - `29d5e02` (feat)

## Files Created/Modified
- `governai/tools/manifest.py` - ToolManifest Pydantic model with all Tool data fields
- `governai/tools/base.py` - Added to_manifest() method, version param, schema_fingerprint attr, hashlib/json imports
- `governai/__init__.py` - Added ToolManifest import and __all__ export
- `tests/test_tool_manifest.py` - 9 test functions covering MFST-01, MFST-02, MFST-03, D-09, D-10

## Decisions Made
- Added `version: str = "0.0.0"` and `schema_fingerprint: str | None = None` to Tool.__init__ in this branch since Phase 1 foundations haven't merged to main yet. This is the same implementation as on codex/release-0.2.0.
- Used lazy import (`from governai.tools.manifest import ToolManifest`) inside to_manifest() to avoid circular dependency since manifest.py imports ExecutionPlacement from base.py.
- ToolManifest imports ExecutionPlacement from governai.tools.base as single source of truth for the Literal type alias.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added version and schema_fingerprint to Tool.__init__**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** Tool class on this branch (main) lacks `version` parameter and `schema_fingerprint` attribute that Phase 1 added on codex/release-0.2.0. Tests and ToolManifest depend on these fields.
- **Fix:** Added `version: str = "0.0.0"` parameter and `self.schema_fingerprint: str | None = None` to Tool.__init__, matching the codex/release-0.2.0 implementation.
- **Files modified:** governai/tools/base.py
- **Verification:** All 104 tests pass, no regressions
- **Committed in:** 29d5e02 (GREEN phase commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential for functionality. Same implementation as Phase 1 branch. No scope creep.

## Issues Encountered
None beyond the deviation above.

## Known Stubs
None - all data fields are wired and functional.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ToolManifest is ready for use by AgentSpec (Plan 02-03) and policy engine
- Tool.to_manifest() provides the extraction mechanism for any tool instance
- Fingerprint computation is self-contained (works with or without ToolRegistry)

## Self-Check: PASSED

- governai/tools/manifest.py: FOUND
- tests/test_tool_manifest.py: FOUND
- 02-02-SUMMARY.md: FOUND
- Commit 117c89f (RED): FOUND
- Commit 29d5e02 (GREEN): FOUND

---
*Phase: 02-serializable-asset-layer*
*Completed: 2026-04-05*
