---
phase: 2
slug: serializable-asset-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` `testpaths = ["tests"]` |
| **Quick run command** | `.venv/bin/pytest tests/test_agent_spec.py tests/test_tool_manifest.py tests/test_atomic_run_store.py -x` |
| **Full suite command** | `.venv/bin/pytest tests/ -q` |
| **Estimated runtime** | ~1 second |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/test_agent_spec.py tests/test_tool_manifest.py tests/test_atomic_run_store.py -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 2 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | SPEC-01 | unit | `.venv/bin/pytest tests/test_agent_spec.py::test_agent_spec_fields -x` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | SPEC-02 | unit | `.venv/bin/pytest tests/test_agent_spec.py::test_agent_from_spec_round_trip -x` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | SPEC-03 | unit | `.venv/bin/pytest tests/test_agent_spec.py::test_agent_spec_json_round_trip -x` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | MFST-01 | unit | `.venv/bin/pytest tests/test_tool_manifest.py::test_tool_manifest_fields -x` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 1 | MFST-02 | unit | `.venv/bin/pytest tests/test_tool_manifest.py::test_tool_to_manifest -x` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02 | 1 | MFST-03 | unit | `.venv/bin/pytest tests/test_tool_manifest.py::test_manifest_carries_all_fields -x` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 2 | PERS-01 | unit | `.venv/bin/pytest tests/test_atomic_run_store.py::test_atomic_write_crash_safety -x` | ❌ W0 | ⬜ pending |
| 02-03-02 | 03 | 2 | PERS-02 | unit | `.venv/bin/pytest tests/test_atomic_run_store.py::test_redis_optimistic_lock_conflict -x` | ❌ W0 | ⬜ pending |
| 02-03-03 | 03 | 2 | PERS-03 | unit | `.venv/bin/pytest tests/test_atomic_run_store.py::test_store_validates_before_write -x` | ❌ W0 | ⬜ pending |
| 02-03-04 | 03 | 2 | D-16 | unit | `.venv/bin/pytest tests/test_atomic_run_store.py::test_v022_fixture_deserializes -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_agent_spec.py` — stubs for SPEC-01, SPEC-02, SPEC-03
- [ ] `tests/test_tool_manifest.py` — stubs for MFST-01, MFST-02, MFST-03
- [ ] `tests/test_atomic_run_store.py` — stubs for PERS-01, PERS-02, PERS-03, D-16
- [ ] `tests/fixtures/run_state_v022.json` — committed v0.2.2 RunState JSON fixture

*No new framework installs needed — pytest 9.0.2 already installed.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 2s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
