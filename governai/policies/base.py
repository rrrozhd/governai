from __future__ import annotations

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
