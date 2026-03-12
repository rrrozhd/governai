from __future__ import annotations

from governai.policies.base import PolicyFunc


def policy(name: str):
    """Policy."""
    def decorator(func: PolicyFunc) -> PolicyFunc:
        """Decorator."""
        setattr(func, "__policy_name__", name)
        return func

    return decorator
