from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from governai.runtime.interrupts import InterruptRequest


class WorkflowError(Exception):
    """Base workflow error."""


class WorkflowDefinitionError(WorkflowError):
    """Raised for invalid workflow definitions."""


class StepNotFoundError(WorkflowError):
    """Raised when a step is missing."""


class IllegalTransitionError(WorkflowError):
    """Raised when a transition is invalid at runtime."""


class BranchResolutionError(WorkflowError):
    """Raised when a branch cannot be resolved."""


class RoutingResolutionError(WorkflowError):
    """Raised when bounded routing cannot be resolved."""


class ApprovalRequiredError(WorkflowError):
    """Raised when approval is needed before execution."""


class ApprovalRejectedError(WorkflowError):
    """Raised when approval is rejected."""


class PolicyDeniedError(WorkflowError):
    """Raised when policy denies execution."""


class ContainmentPolicyError(WorkflowError):
    """Raised when execution placement violates configured containment rules."""


class InterruptError(WorkflowError):
    """Base class for interrupt lifecycle errors."""


class InterruptExpiredError(InterruptError):
    """Raised when resolving an interrupt that has already expired."""

    def __init__(self, message: str, *, request: InterruptRequest) -> None:
        super().__init__(message)
        self.request = request
