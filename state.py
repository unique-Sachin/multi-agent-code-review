from typing import TypedDict, List, Optional, Annotated
import operator


class ReviewState(TypedDict):
    original_code: str
    analysis_report: Annotated[List[str], operator.add]
    security_report: Annotated[List[str], operator.add]
    refactored_code: str
    changes_summary: str
    human_approved: Optional[bool]
    human_feedback: Optional[str]
    test_cases: str
    approved: bool
    review_feedback: str
    confidence_score: float
    iteration_count: int
    max_iterations: int


class ReviewStateUpdate(TypedDict, total=False):
    original_code: str
    analysis_report: List[str]
    security_report: List[str]
    refactored_code: str
    changes_summary: str
    human_approved: Optional[bool]
    human_feedback: Optional[str]
    test_cases: str
    approved: bool
    review_feedback: str
    confidence_score: float
    iteration_count: int
    max_iterations: int