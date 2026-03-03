from pydantic import BaseModel, Field
from typing import List


class AnalysisOutput(BaseModel):
    issues: List[str]


class SecurityOutput(BaseModel):
    vulnerabilities: List[str]


class RefactorOutput(BaseModel):
    refactored_code: str = Field(
        description="The complete refactored source code only. Must contain raw code with no markdown fences, no inline comments about changes, no summaries, and no explanations. Only valid, executable code."
    )
    summary: str = Field(
        description="A concise plain-text summary of what was changed and why. No code snippets."
    )


class ReviewOutput(BaseModel):
    approved: bool
    feedback: str
    confidence_score: float