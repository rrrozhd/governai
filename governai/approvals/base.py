from __future__ import annotations

from abc import ABC, abstractmethod

from governai.models.approval import ApprovalDecision, ApprovalRequest


class BaseApprovalEngine(ABC):
    @abstractmethod
    def create_request(
        self,
        *,
        run_id: str,
        workflow_name: str,
        step_name: str,
        executor_name: str,
        reason: str | None = None,
    ) -> ApprovalRequest:
        """Create request."""
        raise NotImplementedError

    @abstractmethod
    def normalize_decision(self, decision: ApprovalDecision | str) -> ApprovalDecision:
        """Normalize decision."""
        raise NotImplementedError
