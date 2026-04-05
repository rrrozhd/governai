# Roadmap: GovernAI v0.3.0 — Governance Depth

## Overview

This milestone closes 10 identified gaps between GovernAI's current implementation and what Zeroth needs for production-grade governed multi-agent systems. The work is organized into four phases that follow a strict dependency order: foundations first (crash safety + versioning primitives), then serializable assets built on those primitives (unblocking Zeroth Studio), then runtime depth that requires both (capability enforcement, thread lifecycle, secrets, audit enrichment), and finally the memory connector layer that depends on secrets and enrichment being in place. Every phase is additive — no existing public API breaks.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundations** - Policy fault isolation, interrupt TTL enforcement, and contract versioning primitives
- [ ] **Phase 2: Serializable Asset Layer** - AgentSpec, ToolManifest, and transactional state persistence
- [ ] **Phase 3: Runtime Depth** - Capability model, thread lifecycle, secrets-aware context, and audit enrichment
- [ ] **Phase 4: Memory Layer** - Memory connector protocol with scope binding and audit integration

## Phase Details

### Phase 1: Foundations
**Goal**: The policy engine is crash-safe and isolated, interrupted workflows cannot deadlock on expired interrupts, and versioned contract primitives exist for the layers above to build on
**Depends on**: Nothing (first phase)
**Requirements**: POL-01, POL-02, POL-03, INT-01, INT-02, INT-03, CONT-01, CONT-02, CONT-03
**Success Criteria** (what must be TRUE):
  1. A policy that raises an exception or exceeds its declared timeout produces a deny decision with a diagnostic reason — the run continues rather than terminating
  2. Resuming a workflow with an expired interrupt raises InterruptExpiredError instead of silently processing stale data
  3. The interrupt store exposes a sweep API that a caller can invoke to remove all expired interrupt records
  4. RedisInterruptStore uses the async redis.asyncio client (consistent with RedisRunStore — no sync redis.Redis usage in the hot path)
  5. Tools and GovernedStepSpecs carry a version field (SemVer string) and ToolRegistry keys on (name, version) — Zeroth's existing version strings round-trip through the model without re-serialization
**Plans:** 3 plans

Plans:
- [ ] 01-01-PLAN.md — Policy fault isolation (crash safety, per-policy timeout, diagnostic deny decisions)
- [ ] 01-02-PLAN.md — Interrupt async migration (InterruptExpiredError, sweep_expired, redis.asyncio)
- [ ] 01-03-PLAN.md — Contract versioning primitives (version field, (name,version) registry keying, schema fingerprint)

### Phase 2: Serializable Asset Layer
**Goal**: Agent and tool definitions are serializable Pydantic models that Zeroth Studio can store, transmit, and reconstruct — and all state writes are atomic so a crash between write and cache can never leave a run in an inconsistent state
**Depends on**: Phase 1
**Requirements**: SPEC-01, SPEC-02, SPEC-03, MFST-01, MFST-02, MFST-03, PERS-01, PERS-02, PERS-03
**Success Criteria** (what must be TRUE):
  1. An AgentSpec round-trips through model_dump_json() / model_validate_json() with no loss — Agent.from_spec(spec) produces a runtime Agent with identical non-callable configuration
  2. A ToolManifest extracted from a live Tool instance carries input/output schemas, capabilities, placement, and version as JSON-serializable fields
  3. Zeroth's existing flow construction (GovernedFlowSpec + GovernedStepSpec) passes validation unchanged after AgentSpec and ToolManifest land — no new required fields
  4. A crash simulated between state write and cache invalidation leaves the run store in the last successfully committed state (WATCH/MULTI/EXEC atomic write is verified by test)
  5. A v0.2.2-format RunState JSON fixture deserializes without ValidationError after the new persistence layer ships
**Plans:** 3 plans

Plans:
- [ ] 02-01-PLAN.md — AgentSpec serializable descriptor (AgentSpec, ModelSchemaRef, ModelRegistry, to_spec/from_spec)
- [x] 02-02-PLAN.md — ToolManifest read-only descriptor (ToolManifest, Tool.to_manifest() with inline fingerprint)
- [ ] 02-03-PLAN.md — Atomic persistence (WATCH/MULTI/EXEC, epoch CAS, state validation, v0.2.2 fixture)

### Phase 3: Runtime Depth
**Goal**: The policy engine enforces declared capability grants before execution, thread lifecycle is tracked and auditable through all state transitions including archival, secrets are resolved at call time and never appear in persisted audit events, and audit events carry typed extension metadata from consumers
**Depends on**: Phase 2
**Requirements**: CAP-01, CAP-02, CAP-03, THR-01, THR-02, THR-03, SEC-01, SEC-02, SEC-03, AUD-01, AUD-02, AUD-03
**Success Criteria** (what must be TRUE):
  1. A tool that declares a required capability the runtime has not granted produces a deny decision naming the missing capability — the run does not proceed to execution
  2. A ThreadRecord transitions through its full lifecycle (created → active → interrupted → idle → archived) via ThreadStore status transitions — archival is a status change, not a deletion, so the audit trail is preserved
  3. A tool that accesses a secret via SecretsProvider at call time never causes that secret value to appear in any persisted audit event — the emitter's redaction pass replaces known secret values with [REDACTED] before persistence
  4. An AuditEvent with a typed extensions payload serializes and deserializes correctly — a v0.2.2-era AuditEvent without extensions deserializes to extensions=[] without error
**Plans**: TBD
**UI hint**: no

### Phase 4: Memory Layer
**Goal**: Agents can read and write scoped memory through a governed connector protocol that emits typed audit events for all operations and ships a working in-memory default backend
**Depends on**: Phase 3
**Requirements**: MEM-01, MEM-02, MEM-03
**Success Criteria** (what must be TRUE):
  1. A MemoryConnector read or write at any scope (thread, workflow, global) emits a corresponding typed audit event (MEMORY_READ or MEMORY_WRITE) that appears in the audit stream
  2. The built-in DictMemoryConnector works out of the box with no configuration — an alternative backend can be substituted by passing any object that satisfies the MemoryConnector Protocol
  3. Memory connector results are never stored directly in RunState — the runtime holds references or IDs only, keeping RunState size bounded
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundations | 3/3 | Executing | - |
| 2. Serializable Asset Layer | 0/3 | Not started | - |
| 3. Runtime Depth | 0/TBD | Not started | - |
| 4. Memory Layer | 0/TBD | Not started | - |
