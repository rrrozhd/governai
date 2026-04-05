---
phase: 3
slug: runtime-depth
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-05
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/ -x -q --tb=short` |
| **Full suite command** | `python -m pytest tests/ -v --tb=long` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q --tb=short`
- **After every plan wave:** Run `python -m pytest tests/ -v --tb=long`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | AUD-01,AUD-02,AUD-03 | unit | `python -m pytest tests/test_audit_extensions.py -v` | TDD | ⬜ pending |
| 03-02-01 | 02 | 1 | CAP-01,CAP-02,CAP-03 | unit | `python -m pytest tests/test_capability_policy.py -v` | TDD | ⬜ pending |
| 03-03-01 | 03 | 1 | THR-01,THR-02,THR-03 | unit | `python -m pytest tests/test_thread_store.py -v` | TDD | ⬜ pending |
| 03-04-01 | 04 | 2 | SEC-01,SEC-02,SEC-03 | unit | `python -m pytest tests/test_secrets.py -v` | TDD | ⬜ pending |
| 03-04-02 | 04 | 2 | SEC-01,SEC-02,SEC-03,THR-03 | integration | `python -m pytest tests/test_secrets.py -v` | TDD | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

All Phase 3 plans use TDD (`tdd="true"`) — test files are created as the first step of each task (RED phase). No separate Wave 0 stubs are needed because the plans themselves produce the test files before implementation.

- [x] `tests/test_audit_extensions.py` — created by Plan 01 Task 1 (TDD RED step)
- [x] `tests/test_capability_policy.py` — created by Plan 02 Task 1 (TDD RED step)
- [x] `tests/test_thread_store.py` — created by Plan 03 Task 1 (TDD RED step)
- [x] `tests/test_secrets.py` — created by Plan 04 Task 1 (TDD RED step)

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
