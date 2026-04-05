# Phase 1: Foundations - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 01-foundations
**Areas discussed:** Policy failure behavior, Interrupt store migration, Contract version model, Error typing strategy

---

## Policy Failure Behavior

### Q1: When a policy crashes or times out, should the engine continue evaluating remaining policies or short-circuit?

| Option | Description | Selected |
|--------|-------------|----------|
| Fail-closed, stop | Crashing/timed-out policy produces a deny, remaining policies skip. Safest for governance. | ✓ |
| Fail-closed, continue all | Crashing policy produces a deny AND remaining policies still evaluate. Collects all deny reasons. | |
| You decide | Claude picks based on codebase and Zeroth's needs. | |

**User's choice:** Fail-closed, stop
**Notes:** None

### Q2: Should policy timeout be configurable per-policy or also have a global fallback default?

| Option | Description | Selected |
|--------|-------------|----------|
| Per-policy only | Each policy declares its own timeout. No timeout = no enforcement. Matches POL-02. | ✓ |
| Per-policy with global default | Per-policy timeout with a global fallback (e.g. 30s) for policies that don't declare one. | |
| You decide | Claude picks the approach. | |

**User's choice:** Per-policy only
**Notes:** None

### Q3: How should policy timeout/crash diagnostics be surfaced?

| Option | Description | Selected |
|--------|-------------|----------|
| In PolicyDecision.reason | Deny decision includes descriptive reason string. Consistent with existing deny flow. | ✓ |
| Separate diagnostic event | Emit a dedicated audit event for policy failures alongside the deny decision. | |
| You decide | Claude picks based on codebase patterns. | |

**User's choice:** In PolicyDecision.reason
**Notes:** None

---

## Interrupt Store Migration

### Q4: Should we make the InterruptStore ABC async or add a parallel async ABC?

| Option | Description | Selected |
|--------|-------------|----------|
| Make ABC async | All InterruptStore methods become async. Clean API, technically a breaking change. | ✓ |
| New AsyncInterruptStore ABC | Keep sync as-is, add async variant. No breaking change but dual interfaces. | |
| You decide | Claude picks based on Zeroth alignment. | |

**User's choice:** Make ABC async
**Notes:** None

### Q5: Where should the sweep API live?

| Option | Description | Selected |
|--------|-------------|----------|
| On InterruptStore | Store exposes sweep_expired(). Matches INT-02 requirement directly. | ✓ |
| On InterruptManager only | Keep sweep logic in manager. Store stays low-level CRUD. | |
| Both levels | Store has sweep_expired(), manager wraps with epoch awareness. | |

**User's choice:** On InterruptStore
**Notes:** None

### Q6: Should sweep_expired operate across all runs or per-run?

| Option | Description | Selected |
|--------|-------------|----------|
| Global sweep | Cleans all expired interrupts across all runs. Suitable for background maintenance. | ✓ |
| Per-run only | Targets a single run. Safer scope but requires run enumeration. | |
| You decide | Claude picks based on Redis key patterns. | |

**User's choice:** Global sweep
**Notes:** None

---

## Contract Version Model

### Q7: How should ToolRegistry handle versioned lookup?

| Option | Description | Selected |
|--------|-------------|----------|
| (name, version) tuple | Registry keys on (name, version). Exact version lookup. Matches CONT-02. | ✓ |
| (name, version) with latest alias | Same but get('tool_x') without version returns highest registered version. | |
| You decide | Claude picks based on Zeroth's usage patterns. | |

**User's choice:** (name, version) tuple
**Notes:** None

### Q8: Should the version field be required on Tool/GovernedStepSpec, or optional with a default?

| Option | Description | Selected |
|--------|-------------|----------|
| Optional, default '0.0.0' | Existing code works unchanged. Additive change, no breakage. | ✓ |
| Optional, default None | Version is None when unset. Registry falls back to name-only lookup. | |
| Required | All tools must declare a version. Breaking change. | |

**User's choice:** Optional, default '0.0.0'
**Notes:** None

### Q9: When should schema fingerprinting run?

| Option | Description | Selected |
|--------|-------------|----------|
| On registration | Fingerprint computed and stored when tool is registered. No runtime cost per call. | ✓ |
| On demand | Fingerprint computed lazily when requested. | |
| You decide | Claude picks. | |

**User's choice:** On registration
**Notes:** None

---

## Error Typing Strategy

### Q10: Should InterruptExpiredError be a new exception class or reuse an existing hierarchy?

| Option | Description | Selected |
|--------|-------------|----------|
| New class under existing base | Inherits from GovernAI base exception or new InterruptError base. Typed, catchable. | ✓ |
| Standalone exception | No parent hierarchy beyond Exception. Simple but ungrouped. | |
| You decide | Claude designs the exception hierarchy. | |

**User's choice:** New class under existing base
**Notes:** None

### Q11: Should policy timeout/crash produce new exception types or stay within PolicyDecision?

| Option | Description | Selected |
|--------|-------------|----------|
| PolicyDecision deny only | Timeout and crash both produce deny decisions. Consistent with earlier choice. | ✓ |
| New PolicyTimeoutError + PolicyCrashedError | Distinct typed errors. Engine catches but callers can too. | |
| You decide | Claude designs. | |

**User's choice:** PolicyDecision deny only
**Notes:** None

### Q12: Should InterruptExpiredError carry the expired InterruptRequest as context?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, include request | Stores the expired InterruptRequest for diagnostics and audit. | ✓ |
| Just interrupt_id and message | Lightweight error with just ID and message. | |
| You decide | Claude picks. | |

**User's choice:** Yes, include request
**Notes:** None

---

## Claude's Discretion

- Exception hierarchy design details
- blake2b digest size for schema fingerprinting
- asyncio.wait_for implementation details in policy engine
- Redis key patterns for global sweep_expired

## Deferred Ideas

None — discussion stayed within phase scope
