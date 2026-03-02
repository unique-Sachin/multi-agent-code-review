from state import ReviewState, ReviewStateUpdate
from llm import llm
from models import AnalysisOutput, SecurityOutput, RefactorOutput, ReviewOutput
from langgraph.types import interrupt


async def analyzer_agent(state: ReviewState) -> ReviewStateUpdate:
    structured_llm = llm.with_structured_output(AnalysisOutput)

    prompt = f"""
    You are a senior code reviewer.

    Analyze the following code for:
    - Code smells
    - Readability issues
    - Performance concerns

    Code:
    {state["original_code"]}
    """

    result = await structured_llm.ainvoke(prompt)

    return {
        "analysis_report": result.issues
    }


async def security_agent(state):
    structured_llm = llm.with_structured_output(SecurityOutput)

    prompt = f"""
    You are a security expert.

    Analyze the following code for:
    - SQL injection
    - Hardcoded secrets
    - Unsafe eval/exec
    - Insecure deserialization

    Code:
    {state["original_code"]}
    """

    result = await structured_llm.ainvoke(prompt)

    return {
        "security_report": result.vulnerabilities
    }


async def refactor_agent(state):
    structured_llm = llm.with_structured_output(RefactorOutput)
    print(state['review_feedback'])

    human_feedback_section = ""
    if state.get("human_feedback"):
        human_feedback_section = f"""
    Human Reviewer Feedback (must be addressed):
    {state['human_feedback']}
"""

    reviewer_feedback_section = ""
    if state.get("review_feedback"):
        reviewer_feedback_section = f"""
    Automated Reviewer Feedback from previous iteration (must be addressed):
    {state['review_feedback']}
"""

    prompt = f"""
    You are a senior software engineer.

    Original Code:
    {state["original_code"]}

    Code Quality Issues:
    {state["analysis_report"]}

    Security Issues:
    {state["security_report"]}
    {human_feedback_section}{reviewer_feedback_section}
    Refactor the code to:
    - Fix all issues
    - Improve readability
    - Improve security
    - Address any human reviewer feedback
    - Address any automated reviewer feedback
    - Keep functionality intact
    """

    result = await structured_llm.ainvoke(prompt)

    return {
        "refactored_code": result.refactored_code,
        "changes_summary": result.summary,
        "iteration_count": state["iteration_count"] + 1
    }


def human_review_node(state: ReviewState) -> ReviewStateUpdate:
    human_input: dict = interrupt({
        "original_code": state["original_code"],
        "refactored_code": state["refactored_code"],
        "changes_summary": state["changes_summary"],
        "analysis_report": state["analysis_report"],
        "security_report": state["security_report"],
        "prompt": "Review the refactored code and respond with approved (bool) and optional feedback (str)."
    })

    approved: bool = human_input.get("approved", False)
    feedback: str | None = human_input.get("feedback") if not approved else None

    return {
        "human_approved": approved,
        "human_feedback": feedback
    }


async def test_generator_agent(state):
    prompt = f"""
    Write unit tests for the following code:

    {state["refactored_code"]}
    """

    result = await llm.ainvoke(prompt)

    return {
        "test_cases": result.content
    }


async def reviewer_agent(state):
    structured_llm = llm.with_structured_output(ReviewOutput)

    prompt = f"""
    You are a strict senior reviewer.

    Original Issues:
    {state["analysis_report"]}

    Security Issues:
    {state["security_report"]}

    Refactored Code:
    {state["refactored_code"]}

    Check:
    - Were all issues fixed?
    - Is the code secure?
    - Is it clean and production-ready?

    Approve only if everything is properly resolved.
    """

    result = await structured_llm.ainvoke(prompt)

    return {
        "approved": result.approved,
        "review_feedback": result.feedback,
        "confidence_score": result.confidence_score
    }