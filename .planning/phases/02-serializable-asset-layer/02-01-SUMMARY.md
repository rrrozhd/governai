---
phase: 02-serializable-asset-layer
plan: 01
subsystem: agents
tags: [pydantic, serialization, blake2b, protocol, agent-spec]

# Dependency graph
requires:
  - phase: 01-foundations
    provides: "Contract versioning pattern, blake2b fingerprint convention"
provides:
  - "AgentSpec serializable Pydantic model for agent definitions"
  - "ModelSchemaRef for portable model type references"
  - "ModelRegistry runtime-checkable protocol for model resolution"
  - "Agent.to_spec() extraction with blake2b schema fingerprint"
  - "Agent.from_spec() reconstruction via registry"
affects: [02-serializable-asset-layer, zeroth-studio-authoring]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Protocol + runtime_checkable for injectable registries", "Lazy import in method body to avoid circular deps", "blake2b 16-byte digest for schema fingerprinting"]

key-files:
  created:
    - governai/agents/spec.py
    - tests/test_agent_spec.py
  modified:
    - governai/agents/base.py
    - governai/__init__.py

key-decisions:
  - "Field name 'schema' on ModelSchemaRef preserved per plan spec; Pydantic shadow warning suppressed via warnings.catch_warnings at class definition"
  - "to_spec() uses lazy import of AgentSpec/ModelSchemaRef to avoid circular import between base.py and spec.py"
  - "from_spec() requires non-None registry (raises ValueError) per D-05 safety contract"

patterns-established:
  - "Serializable spec pattern: separate non-callable descriptor from runtime class"
  - "ModelRegistry Protocol: runtime-checkable, single resolve(name) method"
  - "Schema fingerprint: blake2b(json.dumps({input, output}, sort_keys=True), digest_size=16).hexdigest()"

requirements-completed: [SPEC-01, SPEC-02, SPEC-03]

# Metrics
duration: 4min
completed: 2026-04-05
---

# Phase 2 Plan 1: AgentSpec Serializable Descriptor Summary

**AgentSpec Pydantic model with JSON round-trip, blake2b schema fingerprint, and ModelRegistry protocol for Agent reconstruction**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-05T14:21:01Z
- **Completed:** 2026-04-05T14:25:16Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 4

## Accomplishments
- Created AgentSpec as a Pydantic BaseModel with all non-callable Agent fields, supporting full JSON round-trip serialization
- Implemented Agent.to_spec() with blake2b schema fingerprint computation (matching ToolRegistry convention)
- Implemented Agent.from_spec() classmethod with ModelRegistry-based model resolution and safety ValueError
- Added ModelRegistry as runtime-checkable Protocol for pluggable model resolution
- Exported AgentSpec, ModelSchemaRef, ModelRegistry from top-level governai package
- 9 new tests, 104 total tests passing (zero regressions)

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests for AgentSpec** - `964f5ff` (test)
2. **Task 1 GREEN: Implement AgentSpec, ModelSchemaRef, ModelRegistry** - `6f05879` (feat)

_TDD task with RED and GREEN commits._

## Files Created/Modified
- `governai/agents/spec.py` - AgentSpec, ModelSchemaRef, ModelRegistry protocol (new)
- `governai/agents/base.py` - Added to_spec() and from_spec() methods on Agent
- `governai/__init__.py` - Added top-level exports for AgentSpec, ModelSchemaRef, ModelRegistry
- `tests/test_agent_spec.py` - 9 tests covering fields, defaults, round-trip, fingerprint, protocol (new)

## Decisions Made
- Preserved `schema` field name on ModelSchemaRef as specified in plan; suppressed Pydantic UserWarning about shadowing deprecated BaseModel.schema using warnings.catch_warnings context manager at class definition time
- Used lazy import of AgentSpec/ModelSchemaRef inside to_spec() method body to prevent circular imports between base.py and spec.py
- from_spec() raises ValueError with descriptive message when registry is None, per D-05 safety contract

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Suppressed Pydantic schema field shadow warning**
- **Found during:** Task 1 GREEN phase
- **Issue:** Pydantic v2 emits UserWarning when a field named `schema` shadows the deprecated BaseModel.schema class method
- **Fix:** Wrapped ModelSchemaRef class definition in `warnings.catch_warnings()` context manager
- **Files modified:** governai/agents/spec.py
- **Verification:** Tests pass with -W error::UserWarning flag
- **Committed in:** 6f05879

**2. [Rule 3 - Blocking] Re-installed editable package for worktree**
- **Found during:** Task 1 GREEN phase
- **Issue:** Editable install pointed to main repo, not worktree; pytest could not find new spec.py module
- **Fix:** Re-installed governai as editable from worktree directory
- **Files modified:** None (pip install only)
- **Verification:** pytest collects and runs all tests successfully

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both fixes necessary for correct test execution. No scope creep.

## Issues Encountered
None beyond the auto-fixed items above.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all functionality is fully wired.

## Next Phase Readiness
- AgentSpec model ready for use by Plan 02 (ToolManifest) and Plan 03 (execution manifests)
- ModelRegistry protocol available for Zeroth Studio integration
- blake2b fingerprint pattern consistent with ToolRegistry convention

## Self-Check: PASSED

- FOUND: governai/agents/spec.py
- FOUND: tests/test_agent_spec.py
- FOUND: .planning/phases/02-serializable-asset-layer/02-01-SUMMARY.md
- FOUND: commit 964f5ff (test RED)
- FOUND: commit 6f05879 (feat GREEN)

---
*Phase: 02-serializable-asset-layer*
*Completed: 2026-04-05*
