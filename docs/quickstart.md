# GovernAI Quickstart

This quickstart gets you from install to your first governed workflow run.

## Install

```bash
uv sync --extra dev
source .venv/bin/activate
```

For the HTTP sandbox worker:

```bash
uv sync --extra dev --extra sandbox
```

For Redis-backed run and interrupt persistence:

```bash
uv sync --extra dev --extra redis
```

## Configure env (for LLM examples)

Create `.env` at repo root:

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

## Minimal governed workflow

```python
from pydantic import BaseModel
from governai import Workflow, step, tool

class In(BaseModel):
    value: int

class Mid(BaseModel):
    value: int

class Out(BaseModel):
    value: int

@tool(name="add_one", input_model=In, output_model=Mid)
async def add_one(ctx, data: In) -> Mid:
    return Mid(value=data.value + 1)

@tool(name="double", input_model=Mid, output_model=Out)
async def double(ctx, data: Mid) -> Out:
    return Out(value=data.value * 2)

class MyFlow(Workflow[In, Out]):
    first = step("first", tool=add_one).then("second")
    second = step("second", tool=double).then_end()

# usage:
# state = await MyFlow().run(In(value=2))
```

## Tools are standalone (LLM optional)

In `governai`, tools are reusable typed executors first. They are not automatically "LLM tools".

You can use the same tool in different ways:
- as a normal deterministic workflow step
- from an agent handler through `ctx.use_tool(...)`
- in custom integration loops (for example with `GovernedToolCallLoop`)

The runtime keeps control of safety and determinism either way.

## Add approval gate for risky side effects

```python
from governai import ApprovalDecision, ApprovalDecisionType

# mark side-effect tool with requires_approval=True in @tool(...)
state = await flow.run(payload)
if state.pending_approval:
    state = await flow.resume(
        state.run_id,
        ApprovalDecision(decision=ApprovalDecisionType.APPROVE, decided_by="alice"),
    )
```

## Use thread-native runs

`run(..., thread_id=...)` is additive. If you omit `thread_id`, GovernAI keeps the old behavior and uses the generated `run_id` as the thread identifier.

```python
state = await flow.run(payload, thread_id="thread-123")
latest = await flow.get_latest_run_state("thread-123")
runs = await flow.list_thread_runs("thread-123")
```

If the latest run for a thread is waiting on approval or an interrupt, you can resume it without keeping your own `thread_id -> run_id` map:

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

## Persist interrupts durably

The default path is in-memory. If you need interrupts to survive process recreation, pass a durable interrupt store.

```python
from governai import RedisInterruptStore

flow = MyFlow(
    interrupt_store=RedisInterruptStore(redis_url="redis://localhost:6379/0"),
)
```

This keeps interrupt requests and per-run interrupt epochs durable while preserving the existing `resume(run_id, ...)` API.

## Add policy checks

```python
from governai import policy, PolicyDecision

@policy("deny_side_effects_without_approval")
def deny_side_effects_without_approval(ctx) -> PolicyDecision:
    approved_steps = set(ctx.metadata.get("approved_steps", []))
    if ctx.side_effect and ctx.step_name not in approved_steps:
        return PolicyDecision(allow=False, reason="approval required")
    return PolicyDecision(allow=True)

flow.runtime.policy_engine.register(deny_side_effects_without_approval)
```

## Inspect audit trail

```python
for event in flow.runtime.audit_emitter.events:
    print(event.event_type, event.step_name, event.payload)
```

## Try included examples

- Script: [`examples/support_flow.py`](../examples/support_flow.py)
- Config/DSL parity script: [`examples/support_flow_from_definitions.py`](../examples/support_flow_from_definitions.py)
- Thread-aware resume script: [`examples/thread_resume.py`](../examples/thread_resume.py)
- Strict remote sandbox example: [`examples/strict_remote_sandbox.py`](../examples/strict_remote_sandbox.py)
- Notebook (LangChain + approval): [`examples/notebooks/governai_support_workflow.ipynb`](../examples/notebooks/governai_support_workflow.ipynb)
- Notebook (LangChain + multi-agent): [`examples/notebooks/governai_multi_agent_workflow.ipynb`](../examples/notebooks/governai_multi_agent_workflow.ipynb)

## Compile from YAML/JSON config

```python
from governai import AgentRegistry, ToolRegistry, governed_flow_from_config

tool_registry = ToolRegistry()  # register tools
agent_registry = AgentRegistry()  # register agents if used

flow = governed_flow_from_config(
    "examples/config/support_flow.yaml",
    tool_registry=tool_registry,
    agent_registry=agent_registry,
    policy_registry={},  # optional mapping: policy_name -> callable
)
```

## Compile from DSL

```python
from governai import AgentRegistry, ToolRegistry, governed_flow_from_dsl

dsl_text = """
flow demo {
  step first: tool support.validate -> end;
}
"""

flow = governed_flow_from_dsl(
    dsl_text,
    tool_registry=ToolRegistry(),
    agent_registry=AgentRegistry(),
)
```

## Choose containment mode

`governai` defaults to host execution in `local_dev` mode. If you need the control plane local but execution remote, use `strict_remote` with a configured sandbox adapter.

```python
from governai import HTTPSandboxExecutionAdapter

flow = MyFlow(
    containment_mode="strict_remote",
    remote_execution_adapter=HTTPSandboxExecutionAdapter(
        base_url="https://sandbox.internal",
        bearer_token="replace-me",
    ),
)
```

More detail: [`docs/sandbox.md`](sandbox.md)

For thread-native execution and durable interrupts: [`docs/threading.md`](threading.md)
