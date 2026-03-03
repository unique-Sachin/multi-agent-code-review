from fastapi import APIRouter, HTTPException

from api.schemas.review import StartRequest, DecisionRequest, StateResponse
from api.services import review as review_service

router = APIRouter(prefix="/api/review", tags=["review"])


@router.post(
    "/start",
    response_model=StateResponse,
    summary="Start a new code review session",
    description=(
        "Submits code to the multi-agent pipeline. "
        "Returns immediately with stage='running' and a thread_id. "
        "Poll GET /{thread_id}/state until stage changes."
    ),
)
async def start_review(body: StartRequest):
    if not body.code.strip():
        raise HTTPException(status_code=422, detail="code must not be empty")
    return await review_service.start_review(body.code.strip(), body.max_iterations)


@router.get(
    "/{thread_id}/state",
    response_model=StateResponse,
    summary="Poll the current state of a review session",
    description=(
        "Returns the current stage: "
        "'running' (agents executing), "
        "'awaiting_review' (paused for human input), "
        "'complete' (finished), or "
        "'error' (pipeline crashed)."
    ),
)
async def get_state(thread_id: str):
    return await review_service.get_state(thread_id)


@router.post(
    "/{thread_id}/decision",
    response_model=StateResponse,
    summary="Submit human review decision",
    description=(
        "Resumes the graph from the human_review interrupt. "
        "Returns immediately with stage='running'. "
        "Poll GET /{thread_id}/state to track progress."
    ),
)
async def submit_decision(thread_id: str, body: DecisionRequest):
    # Guard: don't allow submitting a decision while pipeline is still running
    current = await review_service.get_state(thread_id)
    if current.stage == "running":
        raise HTTPException(
            status_code=409,
            detail="Pipeline is still running — wait until stage is 'awaiting_review'",
        )
    if current.stage == "error":
        raise HTTPException(
            status_code=409,
            detail=f"Pipeline is in error state: {current.error}",
        )
    if current.stage == "complete":
        raise HTTPException(
            status_code=409,
            detail="Review is already complete — start a new session",
        )
    if not body.approved and not (body.feedback or "").strip():
        raise HTTPException(
            status_code=422,
            detail="feedback is required when rejecting the review",
        )
    return await review_service.submit_decision(thread_id, body.approved, body.feedback)


@router.get(
    "/{thread_id}/result",
    response_model=StateResponse,
    summary="Get the final result of a completed review",
    description="Returns the full result payload. Raises 409 if the review is not yet complete.",
)
async def get_result(thread_id: str):
    state = await review_service.get_state(thread_id)
    if state.stage == "running":
        raise HTTPException(status_code=409, detail="Pipeline is still running")
    if state.stage == "error":
        raise HTTPException(status_code=500, detail=f"Pipeline error: {state.error}")
    if state.stage == "awaiting_review":
        raise HTTPException(status_code=409, detail="Review is awaiting human decision")
    return state
