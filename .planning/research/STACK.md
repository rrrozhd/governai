# Stack Research

**Domain:** Python governance framework — v0.3.0 depth features
**Researched:** 2026-04-05
**Confidence:** HIGH (all critical claims verified against installed lockfile, official docs, or PyPI)

---

## Context: What This File Covers

GovernAI v0.3.0 adds 10 depth features to an existing Python 3.12+, Pydantic v2, async-first codebase
already using `redis>=5.0.0`, `langchain`, `langchain-openai`, `lark`, `PyYAML`, and `python-dotenv`.

This file covers only the **new** library needs and patterns. It does not re-research the existing
validated stack.

---

## Key Findings by Feature Area

### 1. Transactional State Persistence — No New Dependencies

**Finding:** The existing `redis>=5.0.0` requirement is already resolved to `redis==7.3.0` in the
lockfile. Redis-py 7.x includes a fully-featured asyncio lock via `redis.asyncio.client.Lock` that
supports `async with client.lock(name, timeout=...)`, atomic acquire/release via Lua script, WATCH
for optimistic locking, and pipeline-based `MULTI/EXEC` transactions natively.

**Pattern to use:** `redis.asyncio` pipeline with `transaction=True` wraps commands in MULTI/EXEC
atomically. For distributed locking use `await client.lock(name, timeout=N)` as an async context
manager — it ships with redis-py, requires no extra package, and is compatible with the existing
`redis.asyncio.from_url(...)` client pattern already in `RedisRunStore`.

**What NOT to add:** `aioredlock` is a separate package implementing the multi-node Redlock
algorithm. GovernAI is a single-process runtime by design. `aioredlock` is overkill and adds
a dependency for distributed correctness guarantees that single-node operation doesn't need.

**Asyncio.Lock for in-memory path:** Python stdlib `asyncio.Lock` is the right pairing for
`InMemoryRunStore` transactions — zero cost, no extra package.

---

### 2. Policy Fault Isolation — No New Dependencies

**Finding:** `asyncio.wait_for()` (stdlib) provides per-policy timeout enforcement. Combined with
`try/except BaseException` wrapping around `await run_policy(...)`, it delivers the required
timeout + exception containment without any new library.

**Pattern to use:**
```python
try:
    decision = await asyncio.wait_for(run_policy(fn, ctx), timeout=policy_timeout)
except asyncio.TimeoutError:
    # policy timed out — treat as deny or log and continue per capability model
except Exception as exc:
    # policy raised — isolate, do not propagate
```

`asyncio.shield()` is available if a policy must not be cancelled mid-flight (e.g., audit-emitting
policies), but should be used selectively.

**Capability model:** Pure Python — a `Capability` enum or frozenset on `PolicyContext` and
`PolicyDecision` is sufficient. No external library required.

---

### 3. Contract Versioning — No New Dependencies

**Finding:** Pydantic v2 exposes `BaseModel.model_json_schema()` which returns a stable `dict`
representing the full JSON schema of any Pydantic model. Hashing that dict with stdlib
`hashlib.blake2b` (available in Python 3.12 standard library without any install) produces a
short, stable fingerprint.

**Pattern to use:**
```python
import hashlib, json

def schema_fingerprint(model_cls) -> str:
    schema_bytes = json.dumps(model_cls.model_json_schema(), sort_keys=True).encode()
    return hashlib.blake2b(schema_bytes, digest_size=16).hexdigest()
```

`blake2b` is ~2x faster than SHA-256 for this use case, produces a 32-char hex digest at
`digest_size=16`, and has been in stdlib since Python 3.6 (well before the 3.12 floor).

**What NOT to add:** `xxhash` (a transitive dependency via langchain) is faster for raw throughput
but is non-cryptographic and non-standard. For a contract fingerprint that could be stored,
audited, or compared across processes, a stdlib hash is preferable for reproducibility guarantees
and zero extra surface area.

---

### 4. AgentSpec / ToolManifest — No New Dependencies

**Finding:** Serializable asset definitions are pure Pydantic v2 BaseModel subclasses with
`model_json_schema()` support and `model_dump_json()` / `model_validate_json()` for persistence.
The Pydantic version already in the lockfile (`2.12.5`) supports all required patterns.

**Pattern to use:** Define `AgentSpec` and `ToolManifest` as `BaseModel` subclasses with
`model_config = ConfigDict(frozen=True)` for immutability. Use `model_json_schema()` output as
the contract fingerprint input (see #3 above). No external registry library needed — a simple
`dict[str, AgentSpec]` in the runtime suffices for v0.3.0.

---

### 5. Rich Thread Lifecycle — No New Dependencies

**Finding:** Thread lifecycle state is an extension of the existing `RunState` Pydantic model
and `RedisRunStore` key schema. The required states (e.g., `created`, `running`, `interrupted`,
`completed`, `archived`) map naturally to a `ThreadStatus` `Literal` or `StrEnum` field.
Archival is a TTL policy on Redis keys — already supported by the `ttl_seconds` parameter on
`RedisRunStore`.

**Pattern to use:** Add a `ThreadRecord` Pydantic model and a `ThreadStore` ABC (analogous to
`RunStore`) with `InMemoryThreadStore` and `RedisThreadStore` implementations. Multi-run
association is a Redis sorted set (`ZADD thread:runs` keyed by timestamp) within the existing
`redis>=5.0.0` client.

---

### 6. Secrets-Aware Execution Context

**Decision: Protocol-only in core; optional extras for backends.**

The `SecretsProvider` interface must be a `typing.Protocol` (not ABC) for structural subtyping
— callers that have their own secrets class should not need to inherit from GovernAI. Mark it
`@runtime_checkable` so `isinstance()` checks work in the runtime dispatch path.

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class SecretsProvider(Protocol):
    async def get(self, key: str) -> str: ...
    async def list_keys(self) -> list[str]: ...
```

**Optional extras (do NOT add to core `dependencies`):**

| Backend | Package | Version | Extra name |
|---------|---------|---------|------------|
| HashiCorp Vault | `hvac` | `>=2.4.0` | `secrets-vault` |
| AWS Secrets Manager | `boto3` | `>=1.34` (or `aioboto3>=12`) | `secrets-aws` |
| Env-var / dotenv | stdlib + `python-dotenv` | already in core | built-in |

`hvac 2.4.0` (latest stable, October 2025) is sync-only. Wrap in `asyncio.to_thread()` for the
async `SecretsProvider` interface — the same pattern already used by `ThreadPoolBackend` in
`execution/backends.py`. Do NOT add `async-hvac` — it is a community fork with lower maintenance
activity than the official hvac.

For AWS, `aioboto3` (async wrapper around boto3) is the cleanest path if async-native is
required. Otherwise `asyncio.to_thread(client.get_secret_value, ...)` on a standard boto3
client is acceptable and avoids the extra dependency.

**Audit redaction:** Secrets values must be scrubbed from `AuditEvent.payload` before emission.
Implement as a `RedactingAuditEmitter` decorator wrapping any `AuditEmitter` — no new library.
The redaction map is a `frozenset[str]` of secret keys injected at context construction time.

---

### 7. Audit Event Enrichment Protocol — No New Dependencies

**Finding:** The existing `AuditEvent` Pydantic model needs a typed extension field. The standard
Pydantic v2 pattern is:

```python
class AuditEvent(BaseModel):
    ...
    extensions: dict[str, Any] = Field(default_factory=dict)
```

For typed extensions, define a `AuditExtension` Protocol (or a thin `BaseModel` base class that
all typed extension models inherit from). Serialization and deserialization via
`model_dump()` / `model_validate()` covers the full round-trip. No third-party event schema
library is needed.

**Pattern to use:** `AuditEmitter.emit()` already accepts `AuditEvent` — enrichment is a
pre-emit transform step. A `EnrichingAuditEmitter` decorator that accepts a list of
`Enricher` callables (each takes `AuditEvent` → `AuditEvent`) is the cleanest approach.

---

### 8. Interrupt TTL Enforcement — No New Dependencies

**Finding:** The `InterruptManager` in `runtime/interrupts.py` already contains `expires_at`,
`clear_expired()`, and epoch-guard logic. TTL enforcement for Redis-backed interrupts needs only
the `EXPIREAT` / `EXPIRE` command already available in `redis>=5.0.0`.

**Pattern to use for Redis TTL on interrupt keys:**
```python
# After save_request, set TTL to match expires_at
await client.expireat(self._request_key(run_id, interrupt_id), request.expires_at)
```

The `expires_at` Unix timestamp is already stored on `InterruptRequest`. The stale-cleanup
path (`clear_expired`) needs an async counterpart for the Redis-backed store — same logic,
using `redis.asyncio`.

**Note:** `RedisInterruptStore` currently uses the sync `redis.Redis` client (not
`redis.asyncio`). This is an existing inconsistency with `RedisRunStore` which uses
`redis.asyncio`. The v0.3.0 interrupt TTL work is a natural moment to migrate
`RedisInterruptStore` to `redis.asyncio` for consistency.

---

### 9. Memory Connector Protocol — Optional Extras Only

**Decision: Protocol-only in core; no new required dependencies.**

Same structural pattern as `SecretsProvider`:

```python
@runtime_checkable
class MemoryConnector(Protocol):
    async def read(self, scope: str, key: str) -> Any: ...
    async def write(self, scope: str, key: str, value: Any) -> None: ...
    async def delete(self, scope: str, key: str) -> None: ...
    async def list_keys(self, scope: str) -> list[str]: ...
```

`scope` binds the connector to a thread/agent context. The audit integration hook is a separate
`AuditEmitter` reference injected into concrete implementations, not the protocol.

**Built-in implementations (no extra package):**
- `InMemoryConnector` — dict-backed, for local_dev mode
- `RedisMemoryConnector` — uses existing `redis>=5.0.0`, behind the `redis` optional extra

**LangChain memory integration:** LangChain has its own `BaseChatMessageHistory` abstractions.
GovernAI should NOT import LangChain types in the `MemoryConnector` Protocol — keep the
protocol decoupled. An adapter that wraps a `MemoryConnector` and exposes `BaseChatMessageHistory`
can live in `governai/integrations/` for Zeroth to use.

---

## Recommended Stack (Additive Changes Only)

### New Optional Extras (additions to pyproject.toml)

| Extra | Package | Version Constraint | When Needed |
|-------|---------|-------------------|-------------|
| `secrets-vault` | `hvac` | `>=2.4.0,<3` | HashiCorp Vault secrets backend |
| `secrets-aws` | `boto3` | `>=1.34` | AWS Secrets Manager backend |
| `secrets-aws-async` | `aioboto3` | `>=12.0` | AWS async-native alternative |

### No New Core Dependencies

All 10 new features are implemented using:

| Capability | Source |
|-----------|--------|
| Distributed lock (Redis path) | `redis.asyncio.Lock` — already in `redis>=5.0.0` |
| In-process lock | `asyncio.Lock` — stdlib |
| Pipeline transactions | `redis.asyncio` pipeline with `transaction=True` — already in `redis>=5.0.0` |
| Policy timeout | `asyncio.wait_for()` — stdlib |
| Schema fingerprint | `hashlib.blake2b` — stdlib |
| Contract versioning | Pydantic `model_json_schema()` — already `pydantic>=2.7,<3` |
| Serializable specs | Pydantic `BaseModel` — already present |
| Thread lifecycle states | `StrEnum` (Python 3.11+ stdlib) + Pydantic model |
| Secrets protocol | `typing.Protocol` — stdlib |
| Memory protocol | `typing.Protocol` — stdlib |
| Audit enrichment | Pydantic `Field(default_factory=dict)` + decorator pattern |
| TTL on interrupts | `redis.asyncio` `EXPIREAT` — already in `redis>=5.0.0` |
| Retry on Redis ops | `tenacity` — already a transitive dependency via langchain |

### Supporting Libraries (Already Present, Use More Actively)

| Library | Resolved Version | New Usage |
|---------|-----------------|-----------|
| `redis` (asyncio) | 7.3.0 | `client.lock()`, `pipeline(transaction=True)`, `expireat()` |
| `pydantic` | 2.12.5 | `model_json_schema()` for fingerprinting, `ConfigDict(frozen=True)` for specs |
| `tenacity` | 9.1.4 | Retry wrapper on Redis persistence operations in `RedisRunStore.put()` |
| `asyncio` | stdlib | `wait_for()` for policy timeout, `Lock` for in-memory path |
| `hashlib` | stdlib | `blake2b` for contract schema hashing |

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Distributed lock | `redis.asyncio.Lock` (built-in) | `aioredlock` | GovernAI is single-process; multi-node Redlock adds complexity for no gain |
| Schema hash | `hashlib.blake2b` (stdlib) | `xxhash` (transitive dep) | Non-cryptographic, no reproducibility guarantees across process restarts |
| Policy timeout | `asyncio.wait_for` (stdlib) | `tenacity` with timeout | `wait_for` is the direct cancellation primitive; tenacity is for retries not timeouts |
| Secrets abstraction | `typing.Protocol` | ABC | Protocol allows structural subtyping — Zeroth's existing secrets classes don't need to inherit from GovernAI |
| Memory abstraction | `typing.Protocol` | LangChain `BaseChatMessageHistory` | Avoids coupling GovernAI core to LangChain's type hierarchy |
| Vault async | `asyncio.to_thread(hvac_call)` | `async-hvac` | `async-hvac` is a community fork with lower maintenance; wrapping sync hvac is simpler |
| Audit enrichment schema | Pydantic dict `extensions` field | `dataclasses.asdict` | Pydantic provides free JSON schema, validation, and round-trip serialization |

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `aioredlock` | Multi-node Redlock is unnecessary for single-process runtime | `redis.asyncio.Lock` built into `redis>=5.0.0` |
| `circuitbreaker` / `pybreaker` / `aiobreaker` | Policy fault isolation is about timeout + exception containment, not circuit state machines | `asyncio.wait_for` + exception wrapping |
| `celery` / `arq` / `rq` | Background scheduling is explicitly out of scope | Not applicable |
| `temporal-sdk` / `prefect` | External workflow engines are out of scope | Not applicable |
| `structlog` / `loguru` | Audit events are typed Pydantic models, not log records | `AuditEmitter` protocol + enrichment decorator |
| `pydantic-settings` | Already using `python-dotenv`; settings pattern is not what's needed here | `SecretsProvider` Protocol for runtime secret resolution |
| `cryptography` | No encryption-at-rest requirement in scope for v0.3.0 | Not applicable |
| Any LangGraph dependency | GovernAI's runtime is self-contained | `LocalRuntime`, `RunStore`, `InterruptManager` |

---

## Integration Points

### redis.asyncio.Lock usage in RedisRunStore.put()

The transactional persist-then-cache pattern requires a lock scoped to a `thread_id`:

```python
lock_key = f"{self.prefix}:lock:thread:{state.thread_id}"
async with (await self._client()).lock(lock_key, timeout=5):
    # MULTI/EXEC pipeline: write snapshot + update thread index atomically
    async with (await self._client()).pipeline(transaction=True) as pipe:
        await pipe.set(self._key(state.run_id), payload, ex=self.ttl_seconds)
        await pipe.rpush(self._thread_run_index_key(state.thread_id), state.run_id)
        await pipe.execute()
```

### Policy timeout in PolicyEngine.evaluate()

```python
import asyncio

async def _run_policy_isolated(self, name, fn, ctx, timeout):
    try:
        return await asyncio.wait_for(run_policy(fn, ctx), timeout=timeout)
    except asyncio.TimeoutError:
        return PolicyDecision(allow=False, reason=f"Policy '{name}' timed out")
    except Exception as exc:
        return PolicyDecision(allow=False, reason=f"Policy '{name}' raised: {exc}")
```

### Contract version fingerprint (standalone function)

```python
import hashlib, json
from pydantic import BaseModel

def contract_fingerprint(model_cls: type[BaseModel]) -> str:
    schema = json.dumps(model_cls.model_json_schema(), sort_keys=True).encode()
    return hashlib.blake2b(schema, digest_size=16).hexdigest()
```

### RedisInterruptStore migration to asyncio

Current `RedisInterruptStore` uses sync `redis.Redis`. v0.3.0 TTL enforcement work should
migrate it to `redis.asyncio.Redis` for consistency with `RedisRunStore`. Migration is a
find-and-replace on the client construction and sync call sites — the existing key schema is
preserved.

---

## Version Compatibility

| Package | Resolved | Constraint | Compatibility Notes |
|---------|---------|------------|---------------------|
| `redis` | 7.3.0 | `>=5.0.0` | `redis.asyncio.Lock`, `pipeline(transaction=True)`, and `expireat()` all available since redis-py 5.x |
| `pydantic` | 2.12.5 | `>=2.7,<3` | `model_json_schema()`, `ConfigDict(frozen=True)`, `model_dump_json()` stable across 2.7–2.12 |
| `tenacity` | 9.1.4 | transitive | `@retry` and `AsyncRetrying` stable; `retry_if_exception_type`, `wait_exponential` available |
| `hvac` | n/a (optional) | `>=2.4.0,<3` | Sync-only; wrap with `asyncio.to_thread()`. Version 2.4.0 released Oct 2025. |
| Python | 3.12+ | project floor | `hashlib.blake2b` stdlib since 3.6. `StrEnum` stdlib since 3.11. `asyncio.wait_for` since 3.4. |

---

## Sources

- [redis-py 7.4.0 Asyncio Examples](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html) — pipeline transaction=True, lock() usage (HIGH confidence)
- [redis-py 7.3.0 lock module](https://redis.readthedocs.io/en/latest/_modules/redis/lock.html) — Lock acquire/release, Lua-based atomic release (HIGH confidence)
- [Redis Distributed Locks official docs](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/) — single-node lock pattern vs Redlock (HIGH confidence)
- [Pydantic JSON Schema docs](https://docs.pydantic.dev/latest/concepts/json_schema/) — model_json_schema(), GenerateJsonSchema (HIGH confidence)
- [Python hashlib docs](https://docs.python.org/3/library/hashlib.html) — blake2b stdlib availability (HIGH confidence)
- [hvac 2.4.0 PyPI](https://pypi.org/project/hvac/) — latest stable Oct 2025 (HIGH confidence)
- [tenacity 9.1.4 PyPI](https://pypi.org/project/tenacity/) — latest stable Feb 2026, AsyncRetrying support (HIGH confidence)
- [Python asyncio-task docs](https://docs.python.org/3/library/asyncio-task.html) — wait_for, shield (HIGH confidence)
- [PEP 544 Protocols](https://peps.python.org/pep-0544/) — runtime_checkable structural subtyping (HIGH confidence)
- uv.lock lockfile — verified resolved versions for redis (7.3.0), pydantic (2.12.5), tenacity (9.1.4) (HIGH confidence)

---

*Stack research for: GovernAI v0.3.0 governance depth features*
*Researched: 2026-04-05*
