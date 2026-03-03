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
    # running        → agents are executing in the background
    # awaiting_review → graph paused at human_review interrupt
    # complete        → graph finished (approved or max iterations reached)
    # error           → an unhandled exception occurred during execution
    stage: Literal["running", "awaiting_review", "complete", "error"]
    iteration_count: int
    # Present only when stage == "awaiting_review"
    interrupt_payload: Optional[InterruptPayload] = None
    # Present only when stage == "complete"
    result: Optional[ResultPayload] = None
    # Present only when stage == "error"
    error: Optional[str] = None
