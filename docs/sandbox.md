# Contained Execution

GovernAI supports two execution modes:

- `local_dev`: default. Tools and agents execute on the same machine as the runtime.
- `strict_remote`: the runtime stays local as the control plane, but governed execution must happen through a remote sandbox.

The control plane always keeps:

- policy evaluation
- approval gates
- audit events
- workflow transitions
- run state and checkpointing

The sandbox only executes tools and agents.

## Executor placement

Placement is configured on the tool or agent object itself.

Tool fields:

- `execution_placement="local_only" | "remote_only" | "local_or_remote"`
- `remote_name: str | None = None`

Agent fields:

- `execution_placement="local_only" | "remote_only" | "local_or_remote"`
- `remote_name: str | None = None`

Behavior:

- `local_only`: host execution only
- `remote_only`: sandbox execution only
- `local_or_remote`: local in `local_dev`, remote in `strict_remote`

`remote_name` defaults to `name` and is used by the sandbox worker to resolve Python tools and agents from its own registries.

## Runtime configuration

Workflow constructors now accept:

- `containment_mode="local_dev" | "strict_remote"`
- `remote_execution_adapter=...`

This applies to:

- `Workflow(...)`
- `governed_flow(...)`
- `governed_flow_from_config(...)`
- `governed_flow_from_dsl(...)`

Example:

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

## Preflight validation

In `strict_remote`, GovernAI fails fast when:

- any workflow step executor is `local_only`
- any agent allowlists a `local_only` tool
- remote-capable executors exist but no `remote_execution_adapter` is configured

This validation runs when the workflow is constructed, not after execution has started.

## HTTP sandbox adapter

Use `HTTPSandboxExecutionAdapter` on the control plane:

```python
from governai import HTTPSandboxExecutionAdapter

adapter = HTTPSandboxExecutionAdapter(
    base_url="https://sandbox.internal",
    bearer_token="replace-me",
)
```

Endpoints:

- `POST /execute/tool`
- `POST /execute/agent`
- `GET /health`

Auth is a static bearer token in the MVP implementation.

## Worker service

Use `create_sandbox_app(...)` on the worker:

```python
from governai import AgentRegistry, ToolRegistry, create_sandbox_app

tool_registry = ToolRegistry()
agent_registry = AgentRegistry()

app = create_sandbox_app(
    tool_registry=tool_registry,
    agent_registry=agent_registry,
    bearer_token="replace-me",
)
```

Python tools and agents are resolved by `remote_name` from the worker-local registries. They are not serialized from the control plane.

CLI tools are executed inside the sandbox environment from the command sent in the remote request.

## Nested agent tool calls

Remote agents do not execute nested tools directly without governance. Instead:

1. the remote agent requests one tool call
2. the control plane evaluates policy/approval and executes that tool
3. the control plane re-invokes the remote agent with the tool result

This keeps governance centralized while still moving execution off-host.

## Boundary guarantees

In `strict_remote`, GovernAI avoids host execution for remote-selected executors:

- no host CLI subprocess for remote CLI tools
- no local `tool.execute(...)` for remote tools
- no local `agent.execute(...)` for remote agents

If you leave a CLI tool as `local_only`, it is still a host subprocess. Containment only exists once that tool is routed through the sandbox.

## End-to-end example

See:

- Example file: [`examples/strict_remote_sandbox.py`](../examples/strict_remote_sandbox.py)
- Tests: [`tests/test_remote_execution.py`](../tests/test_remote_execution.py)
