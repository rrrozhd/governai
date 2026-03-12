# GovernAI Patterns

This guide focuses on implementation patterns for deterministic, governed backend design.

## 1. Deterministic Transition Patterns

### Strict chain
Use when every next step is mandatory.

```python
class StrictFlow(Workflow[In, Out]):
    validate = step("validate", tool=validate_tool).then("fetch")
    fetch = step("fetch", tool=fetch_tool).then("draft")
    draft = step("draft", tool=draft_tool).then_end()
```

### Rule-based branch
Use when output category deterministically chooses branch.

```python
class TriageFlow(Workflow[TriageIn, TriageOut]):
    classify = step("classify", tool=classify_tool).branch(
        router="priority",
        mapping={"high": "escalate", "normal": "draft"},
    )
```

### Bounded routing
Use when executor proposes a route but runtime enforces allowlist.

```python
class RouteFlow(Workflow[In, Out]):
    decide = step("decide", tool=router_tool).route_to(
        allowed=["search_docs", "ask_human", "end"]
    )
```

## 2. Policy Patterns

### Deny by default for side-effect capability

```python
@policy("deny_send_without_approval")
def deny_send_without_approval(ctx) -> PolicyDecision:
    if "email.send" in ctx.capabilities:
        approved = set(ctx.metadata.get("approved_steps", []))
        if ctx.step_name not in approved:
            return PolicyDecision(allow=False, reason="send requires approval")
    return PolicyDecision(allow=True)
```

### Layer global + workflow-specific policies

```python
flow.runtime.policy_engine.register(global_policy)
flow.runtime.policy_engine.register(workflow_policy, workflow_name=flow.name)
```

## 3. Approval Patterns

### Explicit gate by tool metadata

```python
@tool(..., side_effect=True, requires_approval=True)
async def send(...):
    ...
```

### Step-level override

```python
send = step("send", tool=send_tool, approval_override=True).then_end()
```

## 4. Artifact and Context Patterns

### Emit stable artifact keys
Use `emitted_artifact` to avoid brittle dependence on step names.

```python
draft = step("draft", tool=draft_tool, emitted_artifact="draft_v1").then("send")
```

### Use `ctx.get_artifact(...)` for explicit dependency

```python
@tool(...)
async def send(ctx, data):
    draft = ctx.get_artifact("draft_v1")
```

## 5. Multi-Agent Patterns (Governed)

## Agent as bounded step executor

```python
research_agent = Agent(
    name="research_agent",
    ...,
    allowed_tools=["llm.research"],
    allowed_handoffs=["draft_agent"],
    max_turns=1,
    max_tool_calls=1,
)
```

### Handoff from agent handler

```python
async def research_handler(ctx, task):
    out = await ctx.use_tool("llm.research", {"question": task.input_payload["question"]})
    return AgentResult(status="handoff", next_agent="draft_agent", output_payload=out)
```

### Runtime guardrails automatically enforced
- agent tool call must be allowlisted
- max tool-call budget enforced
- handoff must be in agent allowlist
- handoff must match workflow transition
- all handoffs and nested tool calls audited

## 6. Testing Patterns

### Transition tests
- strict ordering
- branch mapping correctness
- bounded routing reject path

### Governance tests
- policy deny before tool execution
- approval interruption/resume
- approval reject -> failed state

### Multi-agent tests
- disallowed tool call rejection
- handoff transition mismatch rejection
- handoff accepted path with expected events
