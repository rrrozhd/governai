# Phase 2: Serializable Asset Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 02-serializable-asset-layer
**Areas discussed:** AgentSpec shape, ToolManifest design, Atomic persistence, Backward compat

---

## AgentSpec Shape

| Option | Description | Selected |
|--------|-------------|----------|
| JSON Schema dicts | Store input_model and output_model as JSON Schema dicts via model_json_schema(). Fully serializable, matches ToolManifest pattern. | ✓ |
| Class references by name | Store as dotted import paths. Tighter coupling but preserves type identity. | |
| You decide | Claude picks the approach that best fits existing patterns. | |

**User's choice:** JSON Schema dicts
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, version + fingerprint | AgentSpec gets version (SemVer, default '0.0.0') and schema_fingerprint (blake2b). Same pattern as Tool. | ✓ |
| Version only, no fingerprint | Add version but skip fingerprint. Schema drift detection may be overkill for agents. | |
| No versioning yet | Keep it simple. Agent versioning in a future phase. | |

**User's choice:** Yes, version + fingerprint
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Tool names only | allowed_tools stays as list[str]. Tool resolution at from_spec() time. | ✓ |
| Tool name + version tuples | list[tuple[str, str]] with (name, version) pairs. Precise but verbose. | |
| Embedded ToolManifests | Inline ToolManifest objects. Self-contained but duplicates data. | |

**User's choice:** Tool names only
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Handler required, models optional | from_spec(spec, handler, input_model=None, output_model=None). Handler always required. | |
| All explicit | from_spec(spec, handler, input_model, output_model). All non-serializable parts required. | |
| Registry-based resolution | from_spec(spec, handler, registry=None). Models resolved from ModelRegistry by name. | ✓ |

**User's choice:** Registry-based resolution
**Notes:** User chose registry-based over explicit args. Models resolved via a ModelRegistry protocol.

| Option | Description | Selected |
|--------|-------------|----------|
| Simple name-based lookup | Protocol with resolve(name: str) -> type[BaseModel]. Minimal. | ✓ |
| Name + version lookup | Protocol with resolve(name: str, version: str) -> type[BaseModel]. More future-proof. | |
| You decide | Claude picks simplest protocol. | |

**User's choice:** Simple name-based lookup
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Schema + name pair | Each model stored as {name: str, schema: dict}. Enables both Studio display and registry reconstruction. | ✓ |
| Name string only | Just the model name. Depends on registry for schema access. | |
| Full Pydantic schema only | JSON Schema dict without name. Self-describing but can't reconstruct. | |

**User's choice:** Schema + name pair
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Agent.to_spec() method | Mirrors Tool.to_manifest() pattern. Extraction logic close to source. | ✓ |
| Standalone extract_spec(agent) | Free function. Keeps Agent class unchanged. | |

**User's choice:** Agent.to_spec() method
**Notes:** —

---

## ToolManifest Design

| Option | Description | Selected |
|--------|-------------|----------|
| Full metadata | All Tool data fields: schemas, version, capabilities, placement, timeout, side_effect, requires_approval, tags, remote_name. | ✓ |
| Schema + identity only | Just name, version, input/output schemas, fingerprint. Minimal. | |
| You decide | Claude picks based on Studio needs. | |

**User's choice:** Full metadata
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| No reconstruction | ToolManifest is read-only metadata. No to_tool() path. | ✓ |
| Yes, with callable injection | ToolManifest.to_tool(execute_fn) creates Tool from manifest + callable. | |
| You decide | Claude picks based on Zeroth usage. | |

**User's choice:** No reconstruction
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — manifest-only policy eval | Policy engine can evaluate capabilities using just the manifest. Enables Studio pre-flight checks. | ✓ |
| No — policy only runs against live Tools | Keep policy evaluation coupled to Tool instances. | |

**User's choice:** Yes — manifest-only policy eval
**Notes:** —

---

## Atomic Persistence

| Option | Description | Selected |
|--------|-------------|----------|
| State + checkpoint index | WATCH the run state key, MULTI/EXEC writes both state payload AND checkpoint index atomically. | ✓ |
| State only, index best-effort | Only state write is atomic. Checkpoint index written separately. | |
| You decide | Claude picks based on PERS-01 requirements. | |

**User's choice:** State + checkpoint index
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Retry with backoff | Up to 3 retries with exponential backoff. Raises StateConcurrencyError if exhausted. | ✓ |
| Fail immediately | Raise immediately on conflict. Let caller decide. | |
| You decide | Claude picks based on single-process constraint. | |

**User's choice:** Retry with backoff
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Store layer | RedisRunStore.put() validates before writing. Store is the gatekeeper. | ✓ |
| Runtime layer | LocalRuntime validates before calling store.put(). Store is dumb persistence. | |
| Both (defense in depth) | Runtime validates first, store validates again. | |

**User's choice:** Store layer
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, epoch-based CAS | InMemoryRunStore uses epoch comparison as CAS. Tests exercise same contract as Redis. | ✓ |
| No, keep it simple | InMemoryRunStore stays as simple dict writes. Only Redis gets atomic semantics. | |
| You decide | Claude decides based on testing strategy. | |

**User's choice:** Yes, epoch-based CAS
**Notes:** —

---

## Backward Compatibility

| Option | Description | Selected |
|--------|-------------|----------|
| Purely additive, no spec changes | AgentSpec and ToolManifest are standalone. No new required fields on GovernedFlowSpec/GovernedStepSpec. | ✓ |
| Optional spec fields on GovernedStepSpec | GovernedStepSpec gets optional agent_spec/tool_manifest fields. | |
| You decide | Claude picks based on 'no new required fields' constraint. | |

**User's choice:** Purely additive, no spec changes
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| JSON fixture test | Commit a real v0.2.2 RunState JSON blob as test fixture. model_validate_json() must succeed. | ✓ |
| Programmatic snapshot | Generate v0.2.2-compatible RunState in test code, serialize, verify. | |
| You decide | Claude picks approach that best catches regressions. | |

**User's choice:** JSON fixture test
**Notes:** —

| Option | Description | Selected |
|--------|-------------|----------|
| Ignore unknown | Pydantic extra='ignore'. Forward-compatible. | |
| Reject unknown (strict) | extra='forbid'. Catches unexpected data early. | |
| You decide | Claude decides based on Zeroth's usage pattern. | ✓ |

**User's choice:** You decide (Claude's discretion)
**Notes:** —

---

## Claude's Discretion

- Unknown field handling on RunState validation (extra='ignore' vs 'forbid')
- Exact retry backoff timing for optimistic lock conflicts
- StateConcurrencyError exception hierarchy placement
- ModelRegistry default implementation (ship with GovernAI or leave to consumers)
- Internal WATCH/MULTI/EXEC pipeline structure (key patterns, TTL within transaction)

## Deferred Ideas

None — discussion stayed within phase scope
