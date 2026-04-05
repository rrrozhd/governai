---
phase: 1
slug: foundations
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~1 second |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 2 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | POL-01 | unit | `python -m pytest tests/test_policy_engine.py -k "exception" -v` | ✅ | ⬜ pending |
| 01-01-02 | 01 | 1 | POL-02 | unit | `python -m pytest tests/test_policy_engine.py -k "timeout" -v` | ✅ | ⬜ pending |
| 01-01-03 | 01 | 1 | POL-03 | unit | `python -m pytest tests/test_policy_engine.py -k "diagnostic" -v` | ✅ | ⬜ pending |
| 01-02-01 | 02 | 1 | INT-01 | unit | `python -m pytest tests/test_interrupt_manager.py -k "expired" -v` | ✅ | ⬜ pending |
| 01-02-02 | 02 | 1 | INT-02 | unit | `python -m pytest tests/test_interrupt_manager.py -k "sweep" -v` | ✅ | ⬜ pending |
| 01-02-03 | 02 | 1 | INT-03 | unit | `python -m pytest tests/test_interrupt_persistence.py -k "async" -v` | ✅ | ⬜ pending |
| 01-03-01 | 03 | 1 | CONT-01 | unit | `python -m pytest tests/test_tool_registry.py -k "version" -v` | ✅ | ⬜ pending |
| 01-03-02 | 03 | 1 | CONT-02 | unit | `python -m pytest tests/test_tool_registry.py -k "fingerprint" -v` | ✅ | ⬜ pending |
| 01-03-03 | 03 | 1 | CONT-03 | unit | `python -m pytest tests/test_tool_registry.py -k "roundtrip" -v` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements.*

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
