from __future__ import annotations


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
