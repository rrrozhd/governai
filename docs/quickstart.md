# GovernAI Quickstart

This quickstart gets you from install to your first governed workflow run.

## Install

```bash
uv sync --extra dev
source .venv/bin/activate
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
