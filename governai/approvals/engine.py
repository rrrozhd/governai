from __future__ import annotations

import uuid

from governai.approvals.base import BaseApprovalEngine
from governai.models.approval import ApprovalDecision, ApprovalDecisionType, ApprovalRequest


class ApprovalEngine(BaseApprovalEngine):
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
        return ApprovalRequest(
            request_id=str(uuid.uuid4()),
            run_id=run_id,
            workflow_name=workflow_name,
            step_name=step_name,
            executor_name=executor_name,
            reason=reason,
        )

    def normalize_decision(self, decision: ApprovalDecision | str) -> ApprovalDecision:
        """Normalize decision."""
        if isinstance(decision, ApprovalDecision):
            return decision
        lowered = decision.lower().strip()
        if lowered == "approve":
            return ApprovalDecision(decision=ApprovalDecisionType.APPROVE)
        if lowered == "reject":
            return ApprovalDecision(decision=ApprovalDecisionType.REJECT)
        raise ValueError("Approval decision must be 'approve' or 'reject'")
