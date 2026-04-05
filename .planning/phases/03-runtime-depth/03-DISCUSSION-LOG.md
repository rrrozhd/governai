# Phase 3: Runtime Depth - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 03-runtime-depth
**Areas discussed:** Capability enforcement, Thread lifecycle, Secrets redaction, Audit extensions

---

## Capability Enforcement

### Q1: Where should capability enforcement live?

| Option | Description | Selected |
|--------|-------------|----------|
| Built-in policy (Recommended) | CapabilityPolicy runs inside PolicyEngine.evaluate() like any other policy. Follows Phase 1 deny pattern. | ✓ |
| Pre-policy gate | Separate check before PolicyEngine.evaluate(). Capability denial skips policy evaluation entirely. | |
| Policy engine hook | Dedicated check_capabilities() method on PolicyEngine that runs first, then regular policies. | |

**User's choice:** Built-in policy
**Notes:** Follows existing policy patterns from Phase 1.

### Q2: How should capability grants be scoped?

| Option | Description | Selected |
|--------|-------------|----------|
| Three tiers: global, workflow, step (Recommended) | CapabilityGrant with scope=global/workflow/step. Matches CAP-02. | ✓ |
| Flat list only | Runtime receives flat set of granted capabilities. No scoping. | |
| Hierarchical with inheritance | Global inherits to workflow, workflow inherits to step. Step-level revoke can override. | |

**User's choice:** Three tiers
**Notes:** None

### Q3: How are capability grants provided to the runtime?

| Option | Description | Selected |
|--------|-------------|----------|
| Constructor injection (Recommended) | LocalRuntime receives grants: list[CapabilityGrant] at init. | ✓ |
| Per-run grants | Grants passed per run_workflow() call. More dynamic. | |
| You decide | Claude decides the injection point. | |

**User's choice:** Constructor injection
**Notes:** None

### Q4: Should the deny decision list both required and granted capabilities?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, full diagnostic (Recommended) | Lists required, granted, and missing capabilities. Matches CAP-03. | ✓ |
| Just missing capabilities | Only list what's missing. Simpler. | |

**User's choice:** Full diagnostic
**Notes:** None

---

## Thread Lifecycle

### Q1: Should ThreadStore be a new standalone ABC or extend RunStore?

| Option | Description | Selected |
|--------|-------------|----------|
| New standalone ABC (Recommended) | ThreadStore is its own ABC. Separate concerns from RunStore. | ✓ |
| RunStore extension | Add thread methods to RunStore ABC. Fewer interfaces. | |
| You decide | Claude decides based on existing patterns. | |

**User's choice:** New standalone ABC
**Notes:** None

### Q2: What state transitions should ThreadRecord support?

| Option | Description | Selected |
|--------|-------------|----------|
| Linear with interrupt (Recommended) | created→active→idle→archived plus active→interrupted→active. | ✓ |
| Free-form status | Any status can transition to any other. | |
| Strict state machine | Explicit allowed-transition map enforced at store level. | |

**User's choice:** Linear with interrupt
**Notes:** None

### Q3: Should ThreadRecord track run_ids?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, list of run_ids (Recommended) | ThreadRecord.run_ids: list[str] for multi-run association. | ✓ |
| No, derive from RunStore | Query RunStore for runs with matching thread_id. | |
| You decide | Claude decides. | |

**User's choice:** Yes, list of run_ids
**Notes:** None

### Q4: Should archival emit an audit event?

| Option | Description | Selected |
|--------|-------------|----------|
| Emit audit event (Recommended) | THREAD_ARCHIVED event type in audit stream. | ✓ |
| Status change only | ThreadStore records transition. Audit implicit. | |
| You decide | Claude decides. | |

**User's choice:** Emit audit event
**Notes:** Consistent with interrupt event pattern.

---

## Secrets Redaction

### Q1: How should SecretsProvider be shaped?

| Option | Description | Selected |
|--------|-------------|----------|
| Protocol with resolve(key) (Recommended) | typing.Protocol with async resolve(key) -> str. NullSecretsProvider default. | ✓ |
| Protocol with resolve + list_keys | Additional list_keys() method. | |
| You decide | Claude decides minimal protocol shape. | |

**User's choice:** Protocol with resolve(key)
**Notes:** Follows Protocol + No-Op Default pattern.

### Q2: Where should redaction happen?

| Option | Description | Selected |
|--------|-------------|----------|
| Emitter-level pre-persist (Recommended) | AuditEmitter wraps emit() with redaction pass before persisting. | ✓ |
| Event construction time | Redaction at AuditEvent creation. | |
| Serialization hook | Custom Pydantic serializer on AuditEvent. | |

**User's choice:** Emitter-level pre-persist
**Notes:** None

### Q3: How should the emitter know which values to redact?

| Option | Description | Selected |
|--------|-------------|----------|
| SecretRegistry tracks resolved values (Recommended) | When resolve() is called, value registered with SecretRegistry. Emitter scans registered values. | ✓ |
| Emitter receives secrets list | Constructor takes list of secret values directly. | |
| You decide | Claude decides tracking mechanism. | |

**User's choice:** SecretRegistry tracks resolved values
**Notes:** None

---

## Audit Extensions

### Q1: How should extensions field be typed?

| Option | Description | Selected |
|--------|-------------|----------|
| list[AuditExtension] (Recommended) | AuditExtension BaseModel with type_key + data. Defaults to []. | ✓ |
| dict[str, Any] | Untyped dict. Simpler but no schema enforcement. | |
| You decide | Claude decides. | |

**User's choice:** list[AuditExtension]
**Notes:** Backward compatible — v0.2.2 events deserialize to extensions=[].

### Q2: Should extensions be validated at emit time?

| Option | Description | Selected |
|--------|-------------|----------|
| Emit time validation (Recommended) | Pydantic validates on construction. Bad data fails immediately. | ✓ |
| Deserialization only | Stored as raw dicts. Validated when reading back. | |
| You decide | Claude decides. | |

**User's choice:** Emit time validation
**Notes:** None

### Q3: How should consumer registration work?

| Option | Description | Selected |
|--------|-------------|----------|
| BaseModel subclass pattern (Recommended) | Consumers define AuditExtension subclasses with type_key discriminator. | ✓ |
| Registry-based | ExtensionRegistry for type_key + schema registration. | |
| You decide | Claude decides. | |

**User's choice:** BaseModel subclass pattern
**Notes:** No central registry needed.

### Q4: Should emitters need special handling for extensions?

| Option | Description | Selected |
|--------|-------------|----------|
| Transparent via model_dump (Recommended) | Pydantic handles serialization. Zero extra code in emitters. | ✓ |
| Custom serializer | Extensions serialize via custom method. | |

**User's choice:** Transparent via model_dump
**Notes:** None

---

## Claude's Discretion

- ThreadRecord field design beyond core fields
- SecretRegistry scope and thread-safety
- CapabilityPolicy registration mechanism
- Thread state transition validation implementation
- New EventType enum values
- NullSecretsProvider error messaging

## Deferred Ideas

None — discussion stayed within phase scope
