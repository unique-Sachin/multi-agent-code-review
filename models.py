from pydantic import BaseModel
from typing import List


class AnalysisOutput(BaseModel):
    issues: List[str]


class SecurityOutput(BaseModel):
    vulnerabilities: List[str]


class RefactorOutput(BaseModel):
    refactored_code: str
    summary: str


class ReviewOutput(BaseModel):
    approved: bool
    feedback: str
    confidence_score: float