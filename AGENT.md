# AGENT.md

Agent/operator guide for working in the `governai` repository.

## Purpose

`governai` is a developer-facing framework for governed AI backends.
The runtime enforces deterministic control flow; tools/agents provide content only.

Core rule:
- Never implement free-form autonomous orchestration.
- Always encode orchestration in workflow transitions.

## Architecture (Source of Truth)

- Tools: `governai/tools/`
- Skills: `governai/skills/`
- Workflows + transitions: `governai/workflows/`
- Runtime loop: `governai/runtime/local.py`
- Policies: `governai/policies/`
- Approvals: `governai/approvals/`
- Audit: `governai/audit/`
- Agents (governed extension): `governai/agents/`
- Models/contracts: `governai/models/`

Public exports are in `governai/__init__.py`.

## Non-Negotiable Design Constraints

1. Determinism first
- Transitions must be explicit (`then`, `branch`, `route_to`).
- Illegal transitions must fail fast.

2. Governance separation
- Runtime decides next step.
- Policy engine decides allow/deny.
- Approval engine decides resume/reject for risky actions.
- Executors (tools/agents) do not mutate workflow control state directly.

3. Typed contracts
- Input/output for tools and agents must be Pydantic models.
- Validate both inbound and outbound payloads.

4. Auditability
- Emit lifecycle events for state changes, execution, policy checks, approvals, transitions, and failures.

5. Bounded multi-agent behavior
- Agents are step executors, not a separate orchestration system.
- Agent tool calls must be allowlisted and bounded by `max_tool_calls`.
- Agent handoffs must be allowlisted and transition-valid.

## Development Workflow

1. Install/sync
```bash
uv sync --extra dev
```

2. Run tests
```bash
.venv/bin/python -m pytest -q
```

3. Example run
```bash
PYTHONPATH=. .venv/bin/python examples/support_flow.py
```

4. Notebooks (LangChain examples)
- `examples/notebooks/governai_support_workflow.ipynb`
- `examples/notebooks/governai_multi_agent_workflow.ipynb`

## Coding Rules for Changes

- Prefer explicit code over magical abstractions.
- Keep runtime logic centralized in `runtime/local.py`.
- Add new features as extensions of existing primitives, not parallel frameworks.
- Preserve backward-compatible API shapes unless change is intentional and documented.
- Add or update tests for every behavior change.

## Testing Expectations

When modifying behavior, update tests in `tests/` for:
- transitions (strict, branch, bounded)
- policy allow/deny effects
- approval interruption/resume/reject
- audit events (happy and failure paths)
- agent tool restrictions and handoff governance

If a bug fix changes runtime behavior, include a regression test.

## Documentation Expectations

Update docs when behavior/API changes:
- `docs/quickstart.md`
- `docs/patterns.md`
- `docs/reference.md`
- `README.md` (if user-visible)

## Env and Secrets

- Local env is `.env` (repo root).
- Do not print secret values in logs/docs.
- If examples need keys, refer to env variable names only.

## Out of Scope (Do Not Add by Default)

- SaaS control plane
- distributed orchestration
- background daemons/schedulers
- unbounded recursive agent swarms
- prompt-driven control flow

## PR/Change Checklist

- [ ] Runtime determinism preserved
- [ ] Policy/approval gates preserved
- [ ] Audit events still emitted correctly
- [ ] Tests added/updated and passing
- [ ] Docs updated for user-facing changes
