# Phase 1: Foundations - Research

**Researched:** 2026-04-05
**Domain:** Python asyncio, policy engine fault isolation, interrupt TTL enforcement, contract versioning primitives
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Policy Fault Isolation**
- **D-01:** Fail-closed, short-circuit — a crashing or timed-out policy produces a deny decision and remaining policies are skipped. The run continues (not terminated) with the deny result.
- **D-02:** Per-policy timeout only — each policy declares its own timeout. No timeout declared means no timeout enforced. No global fallback default. Matches POL-02 and avoids starving legitimate slow policies.
- **D-03:** Diagnostics via PolicyDecision.reason — timeout and crash both produce `PolicyDecision(allow=False, reason='...')` with a descriptive message (e.g., "Policy X timed out after 5s", "Policy X raised ValueError: ..."). No new exception types for policy failures — the engine catches internally and converts to deny.

**Interrupt Store Migration**
- **D-04:** InterruptStore ABC becomes fully async — all methods become async. InMemoryInterruptStore trivially awaits. RedisInterruptStore migrates to redis.asyncio. This is technically a breaking change to the ABC but aligns with the async-first principle.
- **D-05:** Sweep API lives on InterruptStore — `sweep_expired()` is a store-level method per INT-02. Global scope (not per-run) — cleans all expired interrupts across all runs. Suitable for background maintenance callers.

**Contract Version Model**
- **D-06:** ToolRegistry keys on `(name, version)` tuple — `get('tool_x', '1.0.0')` returns exact version. No "latest" alias — callers must specify version. Matches CONT-02.
- **D-07:** Version field is optional, defaults to `'0.0.0'` — existing code that doesn't set a version still works. Additive change, no breakage to existing Tool or GovernedStepSpec usage.
- **D-08:** Schema fingerprint (blake2b on `model_json_schema()`) computed on registration — stored on the tool/manifest. Consumers compare fingerprints to detect schema drift between versions. No runtime cost per tool call.

**Error Typing Strategy**
- **D-09:** InterruptExpiredError is a new exception class under a GovernAI base (or new InterruptError base). Replaces current ValueError on expired interrupt resolution with typed, catchable error.
- **D-10:** InterruptExpiredError carries the full expired InterruptRequest — callers can inspect run_id, step_name, created_at, expires_at for diagnostics and audit.
- **D-11:** Policy failures do NOT produce new exception types — they stay within PolicyDecision deny flow (see D-03). Only interrupts get new typed errors.

### Claude's Discretion
- Exception hierarchy design (whether InterruptError is a new base or reuses existing GovernAI exceptions)
- Exact blake2b digest size for schema fingerprinting
- Internal implementation of asyncio.wait_for wrapping in policy engine
- Redis key patterns for global sweep_expired

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| POL-01 | Policy engine isolates each policy evaluation — a crashing or hung policy does not terminate the run | `_evaluate_policies` in `local.py` runs policies in a for-loop via `run_policy()`; wrapping each call in `try/except + asyncio.wait_for` provides full isolation. Verified working in Python 3.12. |
| POL-02 | Each policy can declare a timeout; engine enforces it via asyncio.wait_for | `PolicyFunc` is currently a bare callable with no timeout attribute. The policy function or the engine needs a per-policy timeout mechanism. `asyncio.wait_for` is the correct primitive; verified raises `TimeoutError` (not `CancelledError`) in Python 3.12 when used in a simple for-loop. |
| POL-03 | Policy exceptions are caught, audited, and converted to deny decisions with diagnostic reason | `PolicyDecision(allow=False, reason=...)` model already exists. `POLICY_CHECKED` and `POLICY_DENIED` audit events already emitted. Only the catch-and-convert logic is missing in `_evaluate_policies`. |
| INT-01 | Interrupt resolution rejects expired interrupts with a typed InterruptExpiredError | `InterruptManager.resolve()` currently raises `ValueError("... has expired")`. Replace with `InterruptExpiredError` carrying the full `InterruptRequest`. `_resume_interrupt` in `local.py` already catches `ValueError` and dispatches `EventType.INTERRUPT_EXPIRED` — update to catch `InterruptExpiredError` instead. |
| INT-02 | InterruptStore provides a sweep API to clean up stale interrupts | `InterruptManager.clear_expired(run_id)` already exists but is per-run. New `sweep_expired()` on the ABC must scan globally (across all runs). For `RedisInterruptStore` this requires a key-scan pattern. |
| INT-03 | RedisInterruptStore uses async Redis client (migrated from sync redis.Redis) | Current `RedisInterruptStore._client()` imports `import redis` (sync). `RedisRunStore._client()` already uses `import redis.asyncio`. Migration is a full rewrite of `RedisInterruptStore` following the `RedisRunStore` async pattern. All store methods become `async def`. `blocking_io` flag removed (no longer needed). |
| CONT-01 | Tools and GovernedStepSpecs carry a version field (SemVer string) | `Tool.__init__()` and `GovernedStepSpec` dataclass need an optional `version: str = '0.0.0'` field. Additive change. |
| CONT-02 | ToolRegistry keys on (name, version) for versioned tool lookup | `ToolRegistry._tools` dict changes from `dict[str, Tool]` to `dict[tuple[str, str], Tool]`. `register()` and `get()` signatures change. Backward compat: callers currently pass only `name` to `get()` — callers must be updated to pass version. |
| CONT-03 | Schema fingerprinting via hashlib.blake2b on Pydantic model_json_schema() detects schema drift | `hashlib.blake2b` in stdlib since Python 3.6. `json.dumps(schema, sort_keys=True).encode()` provides a stable byte representation. Fingerprint computed on `Tool` registration. Stored as a `schema_fingerprint: str` attribute on the tool. |
</phase_requirements>

---

## Summary

Phase 1 implements three independent correctness improvements to the GovernAI policy engine, interrupt store, and contract primitives. All three features use only stdlib primitives and the existing locked dependency set — zero new dependencies are added.

The policy fault isolation work (POL-01, POL-02, POL-03) is a targeted change to `_evaluate_policies` in `local.py` and `run_policy()` in `policies/base.py`. The current implementation has no exception boundary around policy calls — any policy crash terminates the run. The fix is `asyncio.wait_for` wrapping per policy invocation, with a catch block that converts both `TimeoutError` and any `Exception` into a `PolicyDecision(allow=False, reason=...)`. Confirmed working in Python 3.12 — `asyncio.wait_for` raises `TimeoutError` (not `CancelledError`) in a for-loop context.

The interrupt store migration (INT-01, INT-02, INT-03) has two parts: (1) a breaking-but-aligned change to make `InterruptStore` ABC fully async (consistent with `RunStore` which is already fully async), and (2) adding a global `sweep_expired()` on the ABC to complement the existing per-run `clear_expired()` on `InterruptManager`. The `RedisInterruptStore` async migration follows the existing `RedisRunStore` pattern exactly — `_client()` uses `redis.asyncio`. The `_call_interrupt_manager` path in `local.py` (which uses `asyncio.to_thread` for sync stores) is removed once the store becomes natively async.

Contract versioning (CONT-01, CONT-02, CONT-03) adds `version: str = '0.0.0'` to `Tool` and `GovernedStepSpec`, changes `ToolRegistry` to key on `(name, version)`, and computes a `schema_fingerprint` using `hashlib.blake2b` on `model_json_schema()` at registration time. All changes are additive. The fingerprint digest size of 16 bytes (32 hex characters) is appropriate — provides uniqueness without excessive storage.

**Primary recommendation:** Implement in three independent work units — policy isolation, interrupt async migration, contract versioning — each with its own test additions. No cross-unit dependencies within Phase 1.

---

## Standard Stack

### Core (already installed — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncio` | stdlib (Python 3.12) | `wait_for` for per-policy timeout, `TimeoutError` handling | The only correct tool for cooperative timeout in async code |
| `hashlib` | stdlib (Python 3.12) | `blake2b` for schema fingerprinting | Stdlib since 3.6, no dependency, deterministic |
| `pydantic` | 2.12.5 (locked) | `model_json_schema()` for schema fingerprinting input | Already the framework's model layer |
| `redis.asyncio` | 7.3.0 (locked) | Async Redis client for migrated `RedisInterruptStore` | Already used by `RedisRunStore` — migration aligns stores |

### No New Dependencies Required

All Phase 1 work is implementable within the existing locked dependency set. The `redis` optional extra already includes `redis>=5.0.0`, and `redis.asyncio` is part of the `redis` package (not a separate install).

**Version verification:**
```bash
.venv/bin/python -c "import redis; print(redis.__version__)"
# 7.3.0

.venv/bin/python -c "import pydantic; print(pydantic.__version__)"
# 2.12.5
```

---

## Architecture Patterns

### Recommended Project Structure (no new top-level modules)

All Phase 1 changes are modifications to existing files:

```
governai/
├── policies/
│   ├── base.py          # run_policy() — add per-call timeout support
│   └── engine.py        # PolicyEngine.evaluate() — NOT USED (local.py calls _evaluate_policies directly)
├── runtime/
│   ├── local.py         # _evaluate_policies() — add fault isolation loop
│   └── interrupts.py    # InterruptStore ABC (async), InMemoryInterruptStore (async), RedisInterruptStore (async), InterruptExpiredError
├── workflows/
│   └── exceptions.py    # Add InterruptError base + InterruptExpiredError
├── tools/
│   ├── base.py          # Tool.__init__() — add version, schema_fingerprint
│   └── registry.py      # ToolRegistry — change key from str to (name, version) tuple
└── app/
    └── spec.py          # GovernedStepSpec — add version field
```

### Pattern 1: Policy Fault Isolation in `_evaluate_policies`

**What:** Wrap each `run_policy()` call in `try/except + asyncio.wait_for`. Catch `TimeoutError` and any `Exception`. Convert both to `PolicyDecision(allow=False, reason=...)`. Short-circuit: remaining policies are skipped on first deny (per D-01).

**When to use:** Any per-policy evaluation loop.

**Key insight:** The timeout attribute must be discoverable from the policy function itself or from a registration wrapper. Since `PolicyFunc` is currently a bare callable, the cleanest approach is a `__policy_timeout__` attribute set by the `@policy` decorator (or injected at registration time via the `register()` call).

**Example:**
```python
# Source: Python stdlib asyncio docs + direct codebase analysis
async def _evaluate_policies(self, state, workflow, step_name, ctx):
    for policy_name, policy_func in self.policy_engine.policies_for(workflow.name):
        timeout = getattr(policy_func, "__policy_timeout__", None)
        decision = await _run_policy_isolated(policy_func, ctx, policy_name, timeout)
        # emit POLICY_CHECKED audit event (existing)
        if not decision.allow:
            # emit POLICY_DENIED audit event (existing)
            raise PolicyDeniedError(decision.reason or f"Policy denied: {policy_name}")


async def _run_policy_isolated(
    policy_func: PolicyFunc,
    ctx: PolicyContext,
    policy_name: str,
    timeout: float | None,
) -> PolicyDecision:
    try:
        coro = _to_coroutine(policy_func, ctx)
        if timeout is not None:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro
    except asyncio.TimeoutError:
        return PolicyDecision(
            allow=False,
            reason=f"Policy '{policy_name}' timed out after {timeout}s",
        )
    except Exception as exc:
        return PolicyDecision(
            allow=False,
            reason=f"Policy '{policy_name}' raised {type(exc).__name__}: {exc}",
        )
```

**Note:** `asyncio.wait_for` in Python 3.12 raises `TimeoutError` (a subclass of `OSError`, not `CancelledError`) in a plain for-loop. Confirmed with `asyncio.run()` test on this machine.

### Pattern 2: InterruptExpiredError Exception Hierarchy

**What:** Add a typed exception under `WorkflowError` for expired interrupt resolution. `InterruptManager.resolve()` raises it instead of `ValueError`. `_resume_interrupt` in `local.py` catches it by type.

**When to use:** Any code that calls `InterruptManager.resolve()` or needs to distinguish expired-interrupt from other errors.

**Example:**
```python
# governai/workflows/exceptions.py addition
class InterruptError(WorkflowError):
    """Base class for interrupt lifecycle errors."""


class InterruptExpiredError(InterruptError):
    """Raised when resolving an interrupt that has already expired."""

    def __init__(self, message: str, *, request: "InterruptRequest") -> None:
        super().__init__(message)
        self.request = request  # D-10: carries full InterruptRequest
```

```python
# In InterruptManager.resolve() — replace:
#   raise ValueError(f"Interrupt {interrupt_id} has expired")
# with:
raise InterruptExpiredError(
    f"Interrupt {interrupt_id} has expired",
    request=req,
)
```

```python
# In local.py _resume_interrupt — replace:
#   except ValueError as exc:
#       message = str(exc)
#       event = EventType.INTERRUPT_EXPIRED if "expired" in message else ...
# with:
except InterruptExpiredError as exc:
    await self._emit_audit_event(..., event_type=EventType.INTERRUPT_EXPIRED, ...)
    raise
except (ValueError, KeyError) as exc:
    await self._emit_audit_event(..., event_type=EventType.INTERRUPT_REJECTED_EPOCH, ...)
    raise
```

### Pattern 3: Fully Async InterruptStore ABC

**What:** All `InterruptStore` ABC methods become `async def`. `InMemoryInterruptStore` trivially wraps synchronous dict operations with `async def`. `RedisInterruptStore` uses `redis.asyncio` natively. `InterruptManager` all methods become `async def`. `_call_interrupt_manager` in `local.py` is removed — now calls manager methods directly with `await`.

**When to use:** Always — after migration, no sync path exists.

**Model:** Follow `RedisRunStore._client()` exactly:

```python
# governai/runtime/interrupts.py — RedisInterruptStore async migration
class RedisInterruptStore(InterruptStore):
    blocking_io = False  # No longer True — now natively async

    async def _client(self) -> Any:
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as redis  # type: ignore
        except Exception as exc:
            raise RuntimeError("RedisInterruptStore requires 'redis' package") from exc
        self._redis = redis.from_url(self.redis_url, encoding="utf-8", decode_responses=True)
        return self._redis

    async def get_epoch(self, run_id: str) -> int:
        client = await self._client()
        payload = await client.get(self._epoch_key(run_id))
        if payload is None:
            return 0
        return int(payload)

    # ... all other methods follow same pattern
```

**`local.py` simplification after migration:**

```python
# BEFORE (removed):
async def _call_interrupt_manager(self, method, *args, **kwargs):
    if self.interrupt_manager.uses_blocking_io():
        return await asyncio.to_thread(method, *args, **kwargs)
    return method(*args, **kwargs)

# AFTER — direct async calls:
async def _interrupt_resolve(self, **kwargs):
    return await self.interrupt_manager.resolve(**kwargs)
```

### Pattern 4: Global sweep_expired on InterruptStore

**What:** Store-level method that scans all runs and deletes expired records globally. `InMemoryInterruptStore` iterates its `_requests` dict. `RedisInterruptStore` uses a key-scan (`SCAN` command) on the request prefix pattern.

**When to use:** Background maintenance job — a caller invokes this to clean up expired records across all runs. Not called automatically by the runtime.

**Example:**
```python
# In InterruptStore ABC:
@abstractmethod
async def sweep_expired(self) -> int:
    """Delete all expired interrupt requests across all runs. Returns count removed."""

# In InMemoryInterruptStore:
async def sweep_expired(self) -> int:
    now_ts = int(time.time())
    removed = 0
    for run_id in list(self._requests.keys()):
        for interrupt_id, req in list(self._requests.get(run_id, {}).items()):
            if req.expires_at > 0 and req.expires_at <= now_ts:
                self.delete_request_sync(run_id, interrupt_id)  # or inline
                removed += 1
    return removed

# In RedisInterruptStore (key scan pattern):
async def sweep_expired(self) -> int:
    client = await self._client()
    now_ts = int(time.time())
    removed = 0
    cursor = 0
    pattern = f"{self.prefix}:run:*:request:*"
    while True:
        cursor, keys = await client.scan(cursor, match=pattern, count=100)
        for key in keys:
            payload = await client.get(key)
            if payload is None:
                continue
            req_data = json.loads(payload)
            expires_at = req_data.get("expires_at", 0)
            if expires_at > 0 and expires_at <= now_ts:
                await client.delete(key)
                removed += 1
        if cursor == 0:
            break
    return removed
```

**Note on key scan:** Redis `SCAN` with a pattern is O(N) where N is the total key space. For a well-prefixed key space (all interrupt keys share `governai:interrupt:run:*`) this is acceptable for a background maintenance caller. This is not called in the hot path.

### Pattern 5: Contract Versioning

**What:** Add optional `version: str = '0.0.0'` to `Tool` and `GovernedStepSpec`. Compute `schema_fingerprint` on `Tool` registration. Change `ToolRegistry` to key on `(name, version)`.

**Example — Tool version field:**
```python
# governai/tools/base.py
class Tool(Generic[InModelT, OutModelT]):
    def __init__(
        self,
        *,
        name: str,
        version: str = "0.0.0",  # D-07: optional, defaults to '0.0.0'
        # ... existing params ...
    ) -> None:
        self.name = name
        self.version = version
        self.schema_fingerprint: str | None = None  # set on ToolRegistry.register()
        # ... existing assignments ...
```

**Example — ToolRegistry (name, version) keying:**
```python
# governai/tools/registry.py
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[tuple[str, str], Tool] = {}  # keyed on (name, version)
        self._tools_by_remote_name: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        key = (tool.name, tool.version)
        if key in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}@{tool.version}")
        # Compute fingerprint on registration (D-08)
        import hashlib, json
        input_schema = tool.input_model.model_json_schema()
        output_schema = tool.output_model.model_json_schema()
        combined = json.dumps(
            {"input": input_schema, "output": output_schema},
            sort_keys=True,
        ).encode()
        tool.schema_fingerprint = hashlib.blake2b(combined, digest_size=16).hexdigest()
        self._tools[key] = tool
        self._tools_by_remote_name[tool.remote_name] = tool

    def get(self, name: str, version: str = "0.0.0") -> Tool:
        try:
            return self._tools[(name, version)]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}@{version}") from exc
```

**Note on blake2b digest_size:** `digest_size=16` produces a 32-character hex string. Provides 128-bit collision resistance — sufficient for schema drift detection. Confirmed producing stable output.

### Anti-Patterns to Avoid

- **Global policy timeout (out of scope per REQUIREMENTS.md):** No `default_policy_timeout` on `PolicyEngine` or `LocalRuntime`. Per-policy timeout declared on the policy function only.
- **Catching `CancelledError` in policy isolation:** In Python 3.12, `asyncio.wait_for` in a for-loop (not TaskGroup) raises `TimeoutError`, not `CancelledError`. Catching `CancelledError` here would interfere with outer task cancellation. Only catch `TimeoutError` and `Exception` (which does NOT catch `BaseException`/`CancelledError`).
- **`InterruptManager.clear_expired()` as the sweep API:** `clear_expired(run_id)` is per-run. `sweep_expired()` on the store is global. These are different operations serving different callers.
- **Making `GovernedStepSpec.version` required:** D-07 mandates optional with `= '0.0.0'` default. `GovernedStepSpec` is a dataclass — use `field(default='0.0.0')`.
- **Placing schema fingerprint on InterruptStore migration:** Fingerprint computation belongs to `ToolRegistry.register()` only. Do not add to `InterruptManager`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-policy async timeout | Custom coroutine watcher, thread-based timer | `asyncio.wait_for(coro, timeout=N)` | stdlib, integrates natively with event loop, raises `TimeoutError` cleanly |
| Schema fingerprinting | Custom hash scheme, md5/sha256 | `hashlib.blake2b(data, digest_size=16).hexdigest()` | stdlib since 3.6, no deps, cryptographic quality |
| Redis async client for interrupt store | New redis client abstraction layer | `redis.asyncio` (already installed, pattern from `RedisRunStore`) | Avoids dual-client chaos, already tested in the codebase |
| Expired interrupt detection | Custom datetime comparison | `req.expires_at <= int(time.time())` | Already the pattern in `InterruptManager` — stay consistent |

**Key insight:** Phase 1 is a correctness patch on existing primitives. Every tool needed is already in the codebase or stdlib. Introducing new abstractions here risks breaking the downstream layer (Zeroth) that currently works with these primitives.

---

## Common Pitfalls

### Pitfall 1: CancelledError propagation in policy timeout

**What goes wrong:** Developer catches `BaseException` (or `Exception` does not catch `CancelledError`/`KeyboardInterrupt`) in the policy isolation block, or manually raises `CancelledError` thinking it "times out" the task.

**Why it happens:** Python 3.12 `asyncio.wait_for` in a for-loop (not TaskGroup context) raises `TimeoutError` (subclass of `OSError`). `CancelledError` is a subclass of `BaseException`, not `Exception`. Catching `Exception` does NOT catch `CancelledError` — which is correct and intentional.

**How to avoid:** Catch `asyncio.TimeoutError` explicitly (not `BaseException`). Let `CancelledError` propagate unmodified. Confirmed behavior on Python 3.12.12 in this repo.

**Warning signs:** Test for a policy that blocks forever; if the test itself hangs, `CancelledError` is being swallowed.

### Pitfall 2: `_call_interrupt_manager` still in local.py after async migration

**What goes wrong:** After migrating `InterruptStore` to async, the `_call_interrupt_manager` wrapper remains, and the `uses_blocking_io()` path (`asyncio.to_thread`) is still called for the now-async `RedisInterruptStore`.

**Why it happens:** `RedisInterruptStore.blocking_io` was `True` (sync) and the wrapper branched on it. After migration, `blocking_io` should be `False` (or removed), but stale wrapper code may still call `asyncio.to_thread(method)` on an async coroutine function — which would pass the coroutine object (not await it) to `to_thread`, silently dropping the operation.

**How to avoid:** Remove `_call_interrupt_manager` and all `_interrupt_*` wrapper methods from `local.py`. Replace with direct `await self.interrupt_manager.method()` calls. Remove `blocking_io` from `InterruptStore` ABC entirely.

**Warning signs:** `test_interrupt_persistence.py` will fail with `SyncFakeRedis` tests that pass a sync client — those tests must be updated to use `AsyncFakeRedis` patterns (as already done in `test_interrupt_persistence.py:AsyncFakeRedis`).

### Pitfall 3: ToolRegistry callers pass only `name` after (name, version) migration

**What goes wrong:** Existing callers do `registry.get("tool_name")` without a version argument. If `get()` requires two arguments, every caller breaks.

**Why it happens:** The registry currently takes a single string key. Migration to `(name, version)` is a breaking API change for callers.

**How to avoid:** Make `version` a keyword argument with default `"0.0.0"` — `def get(self, name: str, version: str = "0.0.0") -> Tool`. Existing single-argument callers continue to find the tool at version `"0.0.0"` (the default for unversioned tools). Update `local.py` wherever `registry.get(tool_name)` is called to confirm the default behavior is correct.

**Warning signs:** `grep -r "registry.get\|registry.has"` — any single-argument call must be verified to work with the default version.

### Pitfall 4: InterruptManager methods not updated to async when ABC changes

**What goes wrong:** `InterruptStore` ABC methods become `async def`, but `InterruptManager` still calls them synchronously (`self.store.get_epoch(run_id)` instead of `await self.store.get_epoch(run_id)`).

**Why it happens:** `InterruptManager` wraps the store. Both must be updated together. The manager's own methods (`create`, `resolve`, `list_pending`, etc.) also need to become `async def`.

**How to avoid:** After changing the ABC to async, update `InterruptManager` methods to `async def` and add `await` on every store call. Then update `local.py` to `await self.interrupt_manager.resolve(...)` directly (no `_call_interrupt_manager` wrapper).

**Warning signs:** `RuntimeWarning: coroutine '...' was never awaited` in tests — a sure sign a coroutine was called without `await`.

### Pitfall 5: Test infrastructure uses SyncFakeRedis after async migration

**What goes wrong:** `test_interrupt_manager.py` uses `FakeSyncRedis` for `RedisInterruptStore` tests. After the migration to async, `FakeSyncRedis` no longer matches the expected async interface.

**Why it happens:** The test fake was written for the sync store. The new async store calls `await client.get(...)`, `await client.set(...)`, etc. A sync fake will fail immediately at the first `await`.

**How to avoid:** Replace `FakeSyncRedis` in `test_interrupt_manager.py` with the `AsyncFakeRedis` class already present in `test_interrupt_persistence.py`. Or extract a shared `AsyncFakeRedis` fixture to `conftest.py`.

**Warning signs:** `TypeError: object str can't be used in 'await' expression` in interrupt tests.

### Pitfall 6: Schema fingerprint instability from schema key ordering

**What goes wrong:** `model_json_schema()` may produce dicts with varying key order depending on Pydantic internals. Two fingerprints of the same schema differ, causing false drift detection.

**Why it happens:** Python dicts are ordered since 3.7, but Pydantic may add `$defs`, `title`, and other keys in different positions across versions.

**How to avoid:** Always serialize with `json.dumps(schema, sort_keys=True)` before hashing. Confirmed: `hashlib.blake2b(json.dumps(schema, sort_keys=True).encode(), digest_size=16).hexdigest()` produces stable output for identical schemas.

**Warning signs:** Fingerprint differs between two `ToolRegistry.register()` calls for the same tool class.

---

## Code Examples

Verified patterns from codebase analysis and stdlib:

### asyncio.wait_for TimeoutError in Python 3.12
```python
# Verified: raises TimeoutError (not CancelledError) in a plain for-loop
import asyncio

async def slow():
    await asyncio.sleep(10)

async def test():
    try:
        await asyncio.wait_for(slow(), timeout=0.001)
    except asyncio.TimeoutError:
        print("TimeoutError raised — correct")  # This branch executes

asyncio.run(test())
```

### blake2b schema fingerprint
```python
# Verified: produces stable 32-char hex for identical schemas
import hashlib, json
from pydantic import BaseModel

class MyInput(BaseModel):
    value: int

schema = MyInput.model_json_schema()
fingerprint = hashlib.blake2b(
    json.dumps(schema, sort_keys=True).encode(),
    digest_size=16,
).hexdigest()
# e.g., '083a9e8ddc901dc37bbe1e4d1d517802'
```

### InterruptExpiredError with attached request
```python
# Pattern for D-09, D-10
class InterruptExpiredError(InterruptError):
    def __init__(self, message: str, *, request: InterruptRequest) -> None:
        super().__init__(message)
        self.request = request

# Raise site (InterruptManager.resolve):
if req.expires_at <= int(time.time()):
    req.status = "expired"
    await self.store.save_request(req)
    raise InterruptExpiredError(
        f"Interrupt {interrupt_id} has expired",
        request=req,
    )

# Catch site (local.py _resume_interrupt):
except InterruptExpiredError as exc:
    await self._emit_audit_event(
        run_id=state.run_id,
        workflow_name=state.workflow_name,
        step_name=state.current_step,
        event_type=EventType.INTERRUPT_EXPIRED,
        payload={
            "interrupt_id": payload.interrupt_id,
            "error": str(exc),
            "expires_at": exc.request.expires_at,
        },
    )
    raise
```

### Redis async sweep pattern
```python
# Verified: redis.asyncio SCAN API available in redis 7.3.0
import redis.asyncio as redis

async def sweep_expired(self) -> int:
    client = await self._client()
    now_ts = int(time.time())
    removed = 0
    cursor = 0
    pattern = f"{self.prefix}:run:*:request:*"
    while True:
        cursor, keys = await client.scan(cursor, match=pattern, count=100)
        for key in keys:
            payload = await client.get(key)
            if payload is None:
                continue
            data = json.loads(payload)
            if data.get("expires_at", 0) > 0 and data["expires_at"] <= now_ts:
                await client.delete(key)
                removed += 1
        if cursor == 0:
            break
    return removed
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `asyncio.wait_for` raises `CancelledError` on timeout | Raises `TimeoutError` (subclass of `OSError`) | Python 3.11 (PEP 647 area, asyncio change) | Catch `asyncio.TimeoutError` not `CancelledError` — already the right behavior on Python 3.12 |
| Sync `redis.Redis` for interrupt store | `redis.asyncio.Redis` (consistent with run store) | Phase 1 of this milestone | Removes `asyncio.to_thread` wrapper in `local.py`, simplifies runtime |
| `ValueError` for expired interrupt | `InterruptExpiredError(WorkflowError)` carrying the request | Phase 1 of this milestone | Typed, catchable by callers, carries diagnostics |
| Flat string key in `ToolRegistry` | `(name, version)` tuple key | Phase 1 of this milestone | Enables multiple versions of same tool, required by Phase 2 serializable assets |

**Deprecated/outdated after Phase 1:**
- `InterruptStore.blocking_io = True` on `RedisInterruptStore` — replaced by native async; flag removed
- `_call_interrupt_manager` and `_interrupt_*` wrapper methods in `local.py` — replaced by direct `await` calls
- `ValueError` for expired interrupts in `InterruptManager.resolve()` — replaced by `InterruptExpiredError`

---

## Open Questions

1. **Zeroth's existing version string format**
   - What we know: SUMMARY.md and STATE.md flag "Confirm Zeroth's existing version string format in contracts/registry.py before finalizing ContractVersion model." D-07 sets default to `'0.0.0'` — existing tools with no version get this default.
   - What's unclear: Whether Zeroth uses version strings like `'v2-alpha'` or `'1.0.0'` format — this affects whether `'0.0.0'` as the default is the right sentinel, and whether SemVer validation should be strict or permissive.
   - Recommendation: Make the `version` field a plain `str` with no SemVer validation in Phase 1 (per REQUIREMENTS.md wording: "SemVer string"). Zeroth's strings must round-trip without re-serialization (success criterion #5). If Zeroth uses `'v1.0.0'` or `'2-alpha'` strings, a plain `str` field accepts all of them. Add validation only if explicitly required. Planner should add a task to inspect Zeroth's registry before finalizing CONT-01 implementation.

2. **Policy timeout registration mechanism**
   - What we know: `PolicyFunc` is currently `Callable[[PolicyContext], Union[PolicyDecision, Awaitable[PolicyDecision]]]`. Per D-02, each policy declares its own timeout. The `@policy` decorator exists in the codebase.
   - What's unclear: Whether timeout should be set via the `@policy` decorator (`@policy("name", timeout=5.0)`), the `register()` call (`engine.register(fn, timeout=5.0)`), or a `__policy_timeout__` attribute convention.
   - Recommendation: The `__policy_timeout__` attribute convention (set by the decorator or by `register()`) is the least invasive — it doesn't change the `PolicyFunc` type alias or require a new wrapper class. The planner should pick one registration point and document it. Either the decorator or the register call works; both are in-scope for Phase 1.

3. **`InterruptManager` public API continuity**
   - What we know: `InterruptManager` methods (`create`, `resolve`, `list_pending`, etc.) become `async def`. `local.py` currently calls them through `_call_interrupt_manager` which uses `asyncio.to_thread` for blocking stores.
   - What's unclear: Whether `InterruptManager` is directly used by Zeroth (outside of `LocalRuntime`). If Zeroth calls `manager.resolve(...)` synchronously, making it `async def` breaks that callsite.
   - Recommendation: Check Zeroth's codebase for direct `InterruptManager` usage. If none, proceed with async migration. If yes, provide a sync wrapper or defer to a future phase. Based on the public exports in `__init__.py`, `InterruptManager` is exported — assume it may be used directly.

---

## Environment Availability

Step 2.6: All Phase 1 dependencies are stdlib or already installed.

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Python 3.12 | asyncio.wait_for TimeoutError behavior | ✓ | 3.12.12 | — |
| `redis.asyncio` | INT-03 async migration | ✓ | 7.3.0 | — |
| `pydantic` | CONT-03 schema fingerprinting | ✓ | 2.12.5 | — |
| `hashlib` (stdlib) | CONT-03 blake2b | ✓ | stdlib | — |
| `pytest` | Test suite | ✓ | 8.x (via dev extra) | — |

**Baseline:** 95 tests pass in 0.59s on the current HEAD before any Phase 1 changes.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]` |
| Quick run command | `.venv/bin/python -m pytest tests/test_policy_checks.py tests/test_interrupt_manager.py tests/test_interrupt_persistence.py -q` |
| Full suite command | `.venv/bin/python -m pytest -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| POL-01 | Crashing policy produces deny, run continues | unit | `pytest tests/test_policy_checks.py -q` | ✅ (needs new test) |
| POL-02 | Policy with `__policy_timeout__` times out and produces deny | unit | `pytest tests/test_policy_checks.py -q` | ✅ (needs new test) |
| POL-03 | Policy crash captured in `PolicyDecision.reason`, POLICY_DENIED event emitted | unit | `pytest tests/test_policy_checks.py tests/test_audit_events.py -q` | ✅ (needs new test) |
| INT-01 | `InterruptManager.resolve()` raises `InterruptExpiredError` on expired interrupt | unit | `pytest tests/test_interrupt_manager.py -q` | ✅ (needs update: `pytest.raises(InterruptExpiredError)`) |
| INT-02 | `InterruptStore.sweep_expired()` removes expired records globally | unit | `pytest tests/test_interrupt_manager.py -q` | ✅ (needs new test) |
| INT-03 | `RedisInterruptStore` uses `redis.asyncio` — no sync `redis.Redis` in hot path | unit | `pytest tests/test_interrupt_persistence.py tests/test_interrupt_manager.py -q` | ✅ (needs update: drop SyncFakeRedis) |
| CONT-01 | `Tool(name=..., version='1.2.3')` and `GovernedStepSpec(name=..., version='1.2.3')` | unit | `pytest tests/test_tools.py -q` | ✅ (needs new test) |
| CONT-02 | `ToolRegistry.get('name', '1.0.0')` returns versioned tool, unknown version raises `KeyError` | unit | `pytest tests/test_tools.py -q` | ✅ (needs new test) |
| CONT-03 | `Tool.schema_fingerprint` is a 32-char hex string set after `ToolRegistry.register()` | unit | `pytest tests/test_tools.py -q` | ✅ (needs new test) |

### Sampling Rate

- **Per task commit:** `.venv/bin/python -m pytest tests/test_policy_checks.py tests/test_interrupt_manager.py tests/test_interrupt_persistence.py tests/test_tools.py -q`
- **Per wave merge:** `.venv/bin/python -m pytest -q`
- **Phase gate:** Full suite (95+ tests) green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_policy_checks.py` — add `test_policy_crash_produces_deny`, `test_policy_timeout_produces_deny`, `test_policy_crash_reason_in_audit_event`
- [ ] `tests/test_interrupt_manager.py` — update `test_interrupt_expiration_cleanup` to `pytest.raises(InterruptExpiredError)` instead of `pytest.raises(ValueError)`, add `test_sweep_expired_global`
- [ ] `tests/test_interrupt_persistence.py` — replace `SyncFakeRedis` usage in async store tests, update to `AsyncFakeRedis`
- [ ] `tests/test_tools.py` — add `test_tool_version_field_default`, `test_tool_registry_versioned_key`, `test_tool_registry_schema_fingerprint`
- [ ] No new test files needed — all additions fit in existing test modules

---

## Project Constraints (from AGENT.md)

| Directive | Category | Impact on Phase 1 |
|-----------|----------|-------------------|
| Never implement free-form autonomous orchestration | Architecture | No impact — all changes are within existing deterministic flow |
| Keep runtime logic centralized in `runtime/local.py` | Architecture | Policy isolation and interrupt resume logic belong in `local.py` |
| Add new features as extensions of existing primitives, not parallel frameworks | Architecture | Version field on `Tool`/`GovernedStepSpec` is additive; `InterruptExpiredError` extends `WorkflowError` |
| Preserve backward-compatible API shapes unless intentional and documented | API contract | `Tool.version` defaults to `'0.0.0'`; `ToolRegistry.get(name)` defaults `version='0.0.0'`; `InterruptStore` ABC change is intentional (breaking) and must be documented |
| Add or update tests for every behavior change | Testing | Validated — all 9 requirements map to specific test additions above |
| Update docs when behavior/API changes | Documentation | `docs/reference.md` needs update for `ToolRegistry.get()` signature change and `InterruptExpiredError`; `docs/patterns.md` for policy fault isolation pattern |
| Do not print secret values in logs/docs | Security | No impact — Phase 1 does not touch secrets or audit payload content |

---

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis: `governai/policies/engine.py`, `governai/policies/base.py`, `governai/models/policy.py`, `governai/runtime/interrupts.py`, `governai/runtime/local.py` (lines 670-700, 305-370, 1258-1286), `governai/workflows/exceptions.py`, `governai/tools/base.py`, `governai/tools/registry.py`, `governai/app/spec.py`
- Direct test analysis: `tests/test_policy_checks.py`, `tests/test_interrupt_manager.py`, `tests/test_interrupt_persistence.py`
- Python 3.12.12 stdlib verification: `asyncio.wait_for` raises `TimeoutError` (not `CancelledError`) — confirmed with live execution in this repo
- `hashlib.blake2b` stability — confirmed with live execution in this repo
- `redis.asyncio.Redis.from_url` API — confirmed available in redis 7.3.0 installed in `.venv`
- `pyproject.toml` lockfile — redis 7.3.0, pydantic 2.12.5, Python 3.12 minimum
- `AGENT.md` — non-negotiable design constraints

### Secondary (MEDIUM confidence)
- `.planning/research/SUMMARY.md` — Phase 1 feature rationale and pitfall flags (written 2026-04-05 based on broader codebase analysis)
- Python asyncio docs (3.12) — `wait_for` TimeoutError behavior confirmed by execution test above

### Tertiary (LOW confidence — not required for Phase 1)
- Zeroth's `contracts/registry.py` version string format — NOT inspected (out of scope for researcher; flagged as open question for planner)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all claims verified against installed lockfile and live execution
- Architecture: HIGH — based on direct analysis of all affected source files
- Pitfalls: HIGH — all pitfalls are code-specific (verified in source), not speculative
- Test map: HIGH — all existing test files confirmed present, wave 0 gaps specific and actionable

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable stdlib/pydantic/redis patterns — 30 days)
