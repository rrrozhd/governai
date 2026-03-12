from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from governai.models.common import DeterminismMode, normalize_step_ref


@dataclass
class StrictTransition:
    next_step: str

    def __post_init__(self) -> None:
        """Validate and normalize dataclass fields after initialization."""
        self.next_step = normalize_step_ref(self.next_step)


@dataclass
class RuleBasedTransition:
    router: str
    mapping: dict[str, str]

    def __post_init__(self) -> None:
        """Validate and normalize dataclass fields after initialization."""
        self.mapping = {key: normalize_step_ref(value) for key, value in self.mapping.items()}


@dataclass
class BoundedRoutingTransition:
    allowed: list[str]

    def __post_init__(self) -> None:
        """Validate and normalize dataclass fields after initialization."""
        self.allowed = [normalize_step_ref(step) for step in self.allowed]


TransitionConfig = Union[StrictTransition, RuleBasedTransition, BoundedRoutingTransition]


def mode_of(transition: TransitionConfig) -> DeterminismMode:
    """Mode of."""
    if isinstance(transition, StrictTransition):
        return DeterminismMode.STRICT
    if isinstance(transition, RuleBasedTransition):
        return DeterminismMode.RULE_BASED
    return DeterminismMode.BOUNDED_ROUTING
