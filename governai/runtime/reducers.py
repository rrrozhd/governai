from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any


Reducer = Callable[[Any, Any], Any]


def replace_reducer(_: Any, update: Any) -> Any:
    """Replace reducer."""
    return deepcopy(update)


def merge_reducer(current: Any, update: Any) -> Any:
    """Merge reducer."""
    if not isinstance(current, dict):
        current = {}
    if not isinstance(update, dict):
        raise TypeError("merge reducer requires dict update payload")
    merged = dict(current)
    merged.update(update)
    return merged


def append_reducer(current: Any, update: Any) -> Any:
    """Append reducer."""
    if current is None:
        base: list[Any] = []
    elif isinstance(current, list):
        base = list(current)
    else:
        raise TypeError("append reducer requires list current value")
    if isinstance(update, list):
        base.extend(update)
    else:
        base.append(update)
    return base


def clear_reducer(_: Any, __: Any) -> Any:
    """Clear reducer."""
    return None


def prune_reducer(current: Any, update: Any) -> Any:
    """Prune reducer."""
    if isinstance(current, dict):
        if isinstance(update, str):
            out = dict(current)
            out.pop(update, None)
            return out
        if isinstance(update, list):
            out = dict(current)
            for key in update:
                out.pop(str(key), None)
            return out
        raise TypeError("prune reducer on dict requires string or list[str] update")
    if isinstance(current, list):
        if isinstance(update, int):
            return [item for idx, item in enumerate(current) if idx != update]
        if isinstance(update, list):
            idxs = {int(v) for v in update}
            return [item for idx, item in enumerate(current) if idx not in idxs]
        raise TypeError("prune reducer on list requires int or list[int] update")
    return current


class ReducerRegistry:
    def __init__(self) -> None:
        """Initialize ReducerRegistry."""
        self._reducers: dict[str, Reducer] = {
            "replace": replace_reducer,
            "merge": merge_reducer,
            "append": append_reducer,
            "clear": clear_reducer,
            "prune": prune_reducer,
        }

    def register(self, name: str, reducer: Reducer) -> None:
        """Register."""
        if not name:
            raise ValueError("Reducer name must be non-empty")
        self._reducers[name] = reducer

    def resolve(self, name: str) -> Reducer:
        """Resolve."""
        try:
            return self._reducers[name]
        except KeyError as exc:
            raise KeyError(f"Unknown reducer: {name}") from exc

    def names(self) -> list[str]:
        """Names."""
        return sorted(self._reducers.keys())

