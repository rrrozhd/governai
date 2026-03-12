from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from governai.models.approval import ApprovalDecision


class ResumeApproval(BaseModel):
    decision: ApprovalDecision | str


class ResumeInterrupt(BaseModel):
    interrupt_id: str
    response: Any = None
    epoch: int | None = None


ResumePayload = ResumeApproval | ResumeInterrupt

