# Thread-Native Runs And Durable Interrupts

GovernAI now supports caller-supplied thread identity, thread-aware run lookup, and durable interrupt persistence without breaking existing `run_id`-based code.

## Backward compatibility

This remains valid and unchanged:

```python
state = await flow.run(payload)
assert state.thread_id == state.run_id
```

If you do not pass `thread_id`, GovernAI behaves exactly as before.

## Start a run with a caller thread id

```python
state = await flow.run(payload, thread_id="thread-123")
assert state.thread_id == "thread-123"
```

This works on both `Workflow` and `GovernedFlow`.

## Resolve the latest run for a thread

Built-in run stores now track:

- ordered run history per thread
- the active run id for a thread

Lookup semantics are:

1. return the active run for the thread if one exists
2. otherwise return the latest persisted run for the thread
3. raise `KeyError` if the thread has no runs

```python
latest = await flow.get_latest_run_state("thread-123")
history = await flow.list_thread_runs("thread-123")
```

`list_thread_runs(...)` returns run states oldest-to-newest.

## Resume the latest run without your own thread map

If the latest run for a thread is waiting on approval or an interrupt, resume it directly:

```python
from governai import ApprovalDecision, ApprovalDecisionType

state = await flow.resume_latest(
    "thread-123",
    ApprovalDecision(
        decision=ApprovalDecisionType.APPROVE,
        decided_by="alice",
    ),
)
```

This is additive. The existing `resume(run_id, payload)` path is unchanged.

## Inspect pending interrupts

Runtime and workflow surfaces now expose inspection helpers:

```python
pending = await flow.list_pending_interrupts(run_id)
latest = await flow.get_latest_pending_interrupt(run_id)
one = await flow.get_pending_interrupt(run_id, interrupt_id)
thread_pending = await flow.list_thread_pending_interrupts("thread-123")
```

`list_thread_pending_interrupts(...)` requires a thread-aware run store. Built-in in-memory and Redis run stores support it.

## Durable interrupt persistence

Interrupt requests and per-run epochs can now be stored durably.

Available stores:

- `InMemoryInterruptStore`: default path, same lifecycle as the process
- `RedisInterruptStore`: restart-safe persistence for interrupts and epochs

Install Redis support with:

```bash
pip install "governai[redis]"
```

Example:

```python
from governai import RedisInterruptStore

flow = MyFlow(
    interrupt_store=RedisInterruptStore(redis_url="redis://localhost:6379/0"),
)
```

If you already provide a custom `interrupt_manager`, it takes precedence and `interrupt_store` is ignored.

## Audit events

`AuditEvent` now includes a top-level `thread_id` field when available. Event names and payload shapes are unchanged.

```python
for event in flow.runtime.audit_emitter.events:
    print(event.event_type, event.run_id, event.thread_id)
```

## Stores

Built-in run stores:

- `InMemoryRunStore`
- `RedisRunStore`

Both now implement thread-aware lookup and active-run indexing.

Built-in interrupt stores:

- `InMemoryInterruptStore`
- `RedisInterruptStore`

## Example

See the minimal threaded resume example in [`examples/thread_resume.py`](../examples/thread_resume.py).
