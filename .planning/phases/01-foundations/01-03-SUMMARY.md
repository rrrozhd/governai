---
phase: 01-foundations
plan: 03
subsystem: tools
tags: [versioning, blake2b, pydantic, registry, fingerprint]

requires: []
provides:
  - "Tool.version field with '0.0.0' default"
  - "GovernedStepSpec.version field with '0.0.0' default"
  - "(name, version) tuple keying in ToolRegistry"
  - "blake2b schema fingerprinting on tool registration"
affects: [02-assets, contract-serialization, studio-authoring]

tech-stack:
  added: [hashlib-blake2b]
  patterns: [tuple-keyed-registry, schema-fingerprint-on-register]

key-files:
  created: []
  modified:
    - governai/tools/base.py
    - governai/tools/registry.py
    - governai/app/spec.py
    - tests/test_tools.py

key-decisions:
  - "Remote names must be unique across all versions; versioned tools need distinct remote_names"
  - "Schema fingerprint uses blake2b with 16-byte digest (32-char hex) for compact deterministic hashing"

patterns-established:
  - "Tuple keying: registry stores tools as dict[tuple[str, str], Tool] for composite keys"
  - "Fingerprint-on-register: schema fingerprint computed once at registration, not per call"

requirements-completed: [CONT-01, CONT-02, CONT-03]

duration: 2min
completed: 2026-04-05
---

# Phase 1 Plan 3: Contract Versioning Summary

**Version field on Tool and GovernedStepSpec, (name, version)-keyed ToolRegistry, and blake2b schema fingerprinting computed at registration**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-05T11:59:04Z
- **Completed:** 2026-04-05T12:00:57Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added `version` field to Tool (default "0.0.0") and `schema_fingerprint` attribute (None until registration)
- Changed ToolRegistry from string-keyed to (name, version) tuple-keyed, enabling same-name tools at different versions
- Implemented blake2b schema fingerprinting computed from Pydantic model JSON schemas on registration
- Added `version` field to GovernedStepSpec dataclass with "0.0.0" default
- Full backward compatibility: all existing API calls work unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing tests for contract versioning (RED)** - `80f9e95` (test)
2. **Task 2: Implement contract versioning (GREEN)** - `34e3e77` (feat)

## Files Created/Modified
- `governai/tools/base.py` - Added version param and schema_fingerprint attribute to Tool
- `governai/tools/registry.py` - Tuple keying, versioned get/has, blake2b fingerprinting on register
- `governai/app/spec.py` - Added version field to GovernedStepSpec
- `tests/test_tools.py` - 10 new tests for versioning, registry keying, and fingerprinting

## Decisions Made
- Remote names must be unique across all versions -- versioned tools with the same name need distinct remote_names to avoid collisions
- Schema fingerprint uses blake2b with 16-byte digest (32-char hex), chosen for speed and compact output
- Fingerprint computed once at registration time, not per execution call

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed remote_name collision in versioned registry test**
- **Found during:** Task 2 (GREEN phase test run)
- **Issue:** Two tools with name="calc" but different versions defaulted to the same remote_name="calc", causing registration failure
- **Fix:** Updated test to provide distinct remote_names ("calc-v1", "calc-v2") for versioned tools
- **Files modified:** tests/test_tools.py
- **Verification:** All 105 tests pass
- **Committed in:** 34e3e77 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary fix for test correctness. No scope creep.

## Issues Encountered
None

## Known Stubs
None -- all functionality is fully wired.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Contract versioning primitives ready for Phase 2 serializable assets
- ToolRegistry supports versioned lookup needed by ToolManifest and AgentSpec
- Schema fingerprinting enables drift detection between tool versions

## Self-Check: PASSED

- All 4 modified files exist on disk
- Both task commits (80f9e95, 34e3e77) found in git log
- 105 tests passing in full suite

---
*Phase: 01-foundations*
*Completed: 2026-04-05*
