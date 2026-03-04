from pydantic import BaseModel, Field
from typing import Literal, Optional, List


class StartRequest(BaseModel):
    code: str
    max_iterations: int = Field(default=2, ge=1, le=5)


class DecisionRequest(BaseModel):
    approved: bool
    feedback: Optional[str] = None


class InterruptPayload(BaseModel):
    """Payload surfaced to the human reviewer when the graph is interrupted."""
    original_code: str
    refactored_code: str
    changes_summary: str
    analysis_report: List[str]
    security_report: List[str]


class ResultPayload(BaseModel):
    """Final state values returned once the review pipeline is complete."""
    approved: bool
    confidence_score: float
    iteration_count: int
    refactored_code: str
    changes_summary: str
    analysis_report: List[str]
    security_report: List[str]
    review_feedback: str


class StateResponse(BaseModel):
    """Unified response shape for all review endpoints."""
    thread_id: str
    stage: Literal["running", "awaiting_review", "complete", "error"]
    iteration_count: int
    interrupt_payload: Optional[InterruptPayload] = None
    result: Optional[ResultPayload] = None
    error: Optional[str] = None
