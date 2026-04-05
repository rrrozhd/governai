# Requirements: GovernAI

**Defined:** 2026-04-05
**Core Value:** The runtime enforces governance guarantees at the framework layer.

## v1 Requirements

Requirements for v0.3.0 Governance Depth. Each maps to roadmap phases.

### Runtime Correctness

- [ ] **PERS-01**: Runtime persists run state atomically — a crash between write and cache never leaves state inconsistent
- [ ] **PERS-02**: RedisRunStore uses optimistic locking (WATCH/MULTI/EXEC) for compare-and-swap writes
- [ ] **PERS-03**: Runtime validates handoff targets, command state updates, and transitions before persisting state
- [ ] **POL-01**: Policy engine isolates each policy evaluation — a crashing or hung policy does not terminate the run
- [ ] **POL-02**: Each policy can declare a timeout; engine enforces it via asyncio.wait_for
- [ ] **POL-03**: Policy exceptions are caught, audited, and converted to deny decisions with diagnostic reason
- [x] **INT-01**: Interrupt resolution rejects expired interrupts with a typed InterruptExpiredError
- [x] **INT-02**: InterruptStore provides a sweep API to clean up stale interrupts
- [x] **INT-03**: RedisInterruptStore uses async Redis client (migrated from sync redis.Redis)

### Serializable Asset Layer

- [ ] **CONT-01**: Tools and GovernedStepSpecs carry a version field (SemVer string)
- [ ] **CONT-02**: ToolRegistry keys on (name, version) for versioned tool lookup
- [ ] **CONT-03**: Schema fingerprinting via hashlib.blake2b on Pydantic model_json_schema() detects schema drift
- [ ] **SPEC-01**: AgentSpec is a serializable Pydantic model extracting all non-callable fields from Agent
- [ ] **SPEC-02**: Agent.from_spec(spec) factory creates a runtime Agent from an AgentSpec
- [ ] **SPEC-03**: AgentSpec is JSON-serializable via model_dump_json() with schemas as JSON Schema dicts
- [ ] **MFST-01**: ToolManifest is a serializable Pydantic model describing a tool without the Python callable
- [ ] **MFST-02**: Tool.to_manifest() extracts a ToolManifest from a live Tool instance
- [ ] **MFST-03**: ToolManifest carries input/output schemas, capabilities, placement, and version

### Governance Depth

- [ ] **CAP-01**: Tools and agents declare required capabilities; policy engine checks grants before execution
- [ ] **CAP-02**: CapabilityGrant model supports global, workflow-scoped, and step-scoped grants
- [ ] **CAP-03**: Missing capability produces a deny decision with diagnostic listing required vs granted
- [ ] **SEC-01**: SecretsProvider protocol defines resolve(key) -> str for late-bound secret resolution
- [ ] **SEC-02**: ExecutionContext receives an optional SecretsProvider; tools access secrets at call time
- [ ] **SEC-03**: AuditEmitter applies redaction pass — known secret values are replaced with [REDACTED] before persistence
- [ ] **AUD-01**: AuditEvent carries a typed extensions field for consumer-provided metadata
- [ ] **AUD-02**: AuditExtensionProtocol defines how extensions are registered and serialized
- [ ] **AUD-03**: Emitters serialize extensions alongside base event fields transparently

### Thread & Memory

- [ ] **THR-01**: ThreadRecord model tracks lifecycle states (created, active, idle, interrupted, archived)
- [ ] **THR-02**: ThreadStore provides CRUD operations for thread records with status transitions
- [ ] **THR-03**: Thread archival is a status transition, not deletion — preserves audit trail
- [ ] **MEM-01**: MemoryConnector protocol defines read/write/search with scope binding (thread, workflow, global)
- [ ] **MEM-02**: Memory writes emit audit events (MEMORY_WRITE, MEMORY_READ event types)
- [ ] **MEM-03**: In-memory MemoryConnector implementation ships as default; backends are pluggable

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Extended Persistence

- **PERS-04**: Distributed lock interface (SET NX PX) for multi-process deployments
- **PERS-05**: Event-sourced run state for full replay capability

### Extended Governance

- **CAP-04**: Dynamic capability grants that can be added/revoked mid-workflow
- **SEC-04**: HashiCorp Vault backend for SecretsProvider
- **SEC-05**: AWS Secrets Manager backend for SecretsProvider

### Extended Memory

- **MEM-04**: Redis-backed MemoryConnector implementation
- **MEM-05**: Vector store MemoryConnector for semantic search
- **MEM-06**: Memory retention policies (TTL-based expiry per scope)

### Extended Authoring

- **CONT-04**: Schema migration hook (contract_migrate) for version coercion
- **SPEC-04**: AgentSpec composition (agent inherits from base spec)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full distributed locking (REDLOCK) | Over-engineering for single-process runtime; optimistic locking sufficient |
| Schema migration engine (auto version coercion on reads) | Couples persistence to business logic; migration is an application concern |
| Agent-level memory in RunState | Unbounded RunState growth; use MemoryConnector protocol instead |
| Thread hard deletion | Loses audit trail; archival via status transition preserves compliance |
| Global shared policy timeout | Starves legitimate slow policies; per-policy timeout is correct |
| Secrets stored in RunState or audit payload | Regulatory violation; use SecretsProvider with emitter-level redaction |
| SaaS control plane | Not a hosted service; Zeroth owns this layer |
| Visual builder UI | Zeroth Studio owns this layer |
| Distributed orchestration | Single-process runtime by design |
| Auth/RBAC | Zeroth owns identity; GovernAI provides capability hooks |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PERS-01 | Phase 2 | Pending |
| PERS-02 | Phase 2 | Pending |
| PERS-03 | Phase 2 | Pending |
| POL-01 | Phase 1 | Pending |
| POL-02 | Phase 1 | Pending |
| POL-03 | Phase 1 | Pending |
| INT-01 | Phase 1 | Complete |
| INT-02 | Phase 1 | Complete |
| INT-03 | Phase 1 | Complete |
| CONT-01 | Phase 1 | Pending |
| CONT-02 | Phase 1 | Pending |
| CONT-03 | Phase 1 | Pending |
| SPEC-01 | Phase 2 | Pending |
| SPEC-02 | Phase 2 | Pending |
| SPEC-03 | Phase 2 | Pending |
| MFST-01 | Phase 2 | Pending |
| MFST-02 | Phase 2 | Pending |
| MFST-03 | Phase 2 | Pending |
| CAP-01 | Phase 3 | Pending |
| CAP-02 | Phase 3 | Pending |
| CAP-03 | Phase 3 | Pending |
| SEC-01 | Phase 3 | Pending |
| SEC-02 | Phase 3 | Pending |
| SEC-03 | Phase 3 | Pending |
| AUD-01 | Phase 3 | Pending |
| AUD-02 | Phase 3 | Pending |
| AUD-03 | Phase 3 | Pending |
| THR-01 | Phase 3 | Pending |
| THR-02 | Phase 3 | Pending |
| THR-03 | Phase 3 | Pending |
| MEM-01 | Phase 4 | Pending |
| MEM-02 | Phase 4 | Pending |
| MEM-03 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 33 total
- Mapped to phases: 33
- Unmapped: 0

---
*Requirements defined: 2026-04-05*
*Last updated: 2026-04-05 after roadmap creation*
