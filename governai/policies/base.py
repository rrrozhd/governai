from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Union

from governai.models.policy import PolicyContext, PolicyDecision

PolicyFunc = Callable[[PolicyContext], Union[PolicyDecision, Awaitable[PolicyDecision]]]


async def run_policy(policy_func: PolicyFunc, ctx: PolicyContext) -> PolicyDecision:
    """Run policy."""
    result = policy_func(ctx)
    if inspect.isawaitable(result):
        result = await result
    return result


async def _run_policy_isolated(
    policy_func: PolicyFunc,
    ctx: PolicyContext,
    policy_name: str,
    timeout: float | None,
) -> PolicyDecision:
    """Run a single policy with crash and timeout isolation.

    Per D-01: Exceptions produce deny. Per D-02: timeout from __policy_timeout__.
    Per D-03: Diagnostic reason in PolicyDecision.reason.
    """
    try:
        coro = run_policy(policy_func, ctx)
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
