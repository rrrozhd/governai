# GovernAI

## What This Is

A developer-facing Python framework for building governed AI backends with deterministic, auditable execution. Provides typed tool contracts, runtime-enforced workflow transitions, policy/approval gates, and audit event streams. Primary consumer is Zeroth, a governed medium-code platform for multi-agent systems built on top of GovernAI's runtime abstractions.

## Core Value

The runtime — not prompts, not application code — enforces what runs next, what is allowed, what needs approval, and what gets audited. Governance guarantees live at the framework layer.

## Current Milestone: v0.3.0 Governance Depth

**Goal:** Close the 10 identified gaps between GovernAI's current implementation and what Zeroth needs for production-grade governed multi-agent systems.

**Target features:**
- Transactional state persistence with atomic persist-then-cache and distributed locking
- Policy fault isolation with per-policy timeout, exception handling, and capability model
- Contract versioning as a first-class primitive on tools and step specs
- Serializable agent asset definitions (AgentSpec) separate from runtime instances
- Execution manifest model (ToolManifest) for declarative, serializable tool definitions
- Rich thread lifecycle model with states, multi-run association, and archival
- Secrets-aware execution context with runtime resolution and automatic audit redaction
- Audit event enrichment protocol for typed extension metadata
- Interrupt TTL enforcement with expiration checks and stale cleanup
- Memory connector protocol with scope binding, audit integration, and pluggable backends

## Requirements

### Validated

- Typed tool contracts (Python + CLI) with Pydantic validation — v0.1.0
- Deterministic workflow chaining (strict/branch/bounded transitions) — v0.1.0
- Runtime-enforced control flow — v0.1.0
- Policy checks before execution — v0.1.0
- Approval interruptions before risky actions — v0.1.0
- Full audit event streams — v0.1.0
- Governed multi-agent with allowlisted tools/handoffs — v0.1.0
- GovernedFlowSpec app layer with config/DSL frontends — v0.1.0
- Thread-native execution with durable interrupts — v0.2.0
- Contained execution (local_dev / strict_remote) — v0.2.0
- Redis-backed run, interrupt, and audit persistence — v0.2.0

### Active

- [x] Transactional state persistence — Validated in Phase 2: Serializable Asset Layer
- [x] Policy fault isolation and capability model — Validated in Phase 1: Foundations
- [x] Contract versioning — Validated in Phase 1: Foundations
- [x] Agent asset definitions (AgentSpec) — Validated in Phase 2: Serializable Asset Layer
- [x] Execution manifest model (ToolManifest) — Validated in Phase 2: Serializable Asset Layer
- [ ] Rich thread lifecycle
- [ ] Secrets-aware execution context
- [ ] Audit event enrichment protocol
- [x] Interrupt TTL enforcement — Validated in Phase 1: Foundations
- [ ] Memory connector protocol

### Out of Scope

- SaaS control plane — not a hosted service
- Visual builder UI — Zeroth Studio owns this layer
- Distributed orchestration — single-process runtime by design
- Temporal integration — not adopting external workflow engines
- Auth/RBAC — Zeroth owns identity; GovernAI provides capability hooks
- Background scheduling — synchronous execution model
- Autonomous free-form swarms — agents are bounded step executors

## Context

- **Primary consumer**: Zeroth depends on GovernAI via local path. Zeroth's graph models compile to GovernedFlowSpec/GovernedStepSpec. Zeroth's Run extends RunState. Zeroth uses RedisRunStore, RedisInterruptStore, RedisAuditEmitter directly.
- **Workarounds in Zeroth**: Contract versioning (contracts/registry.py), execution manifests (execution_units/adapters.py), thread lifecycle (runs/models.py), policy guards (policy/), secrets (secrets/), memory (memory/), enriched audit (audit/). Each is a parallel system that should be consolidated into GovernAI primitives.
- **Studio dependency**: Zeroth Phase 10+ (Studio authoring) is blocked on contract versioning, agent specs, and execution manifests being serializable at the GovernAI layer.
- **Python**: 3.12+, Pydantic v2, async-first.

## Constraints

- **Backward compatibility**: Existing GovernAI public API must not break. New features are additive.
- **Zeroth alignment**: New abstractions should match Zeroth's existing patterns so migration is straightforward.
- **No new required dependencies**: New protocols (secrets, memory) should be abstract; implementations are optional extras.
- **Performance**: deepcopy and persistence patterns must handle realistic artifact sizes without degradation.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Zeroth is the primary design driver | Only real consumer; abstract later | -- Pending |
| Additive API changes only | Zeroth v1.0 runtime is shipped and working | -- Pending |
| Protocols over implementations | Secrets, memory, audit extensions are pluggable | -- Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check -- still the right priority?
3. Audit Out of Scope -- reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-05 after Phase 2 (Serializable Asset Layer) complete*
