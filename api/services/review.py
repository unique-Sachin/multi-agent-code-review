import asyncio
import uuid
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from graph import build_graph
from state import ReviewState
from api.schemas.review import StateResponse, InterruptPayload, ResultPayload

_graph = None

# ---------------------------------------------------------------------------
# In-memory session tracker
# Tracks threads that are actively running or have errored.
# { thread_id: ("running" | "error", error_message_or_None) }
# When a thread finishes successfully it is removed — get_state then falls
# through to the LangGraph checkpoint to determine the real stage.
# ---------------------------------------------------------------------------
_sessions: dict[str, tuple[str, str | None]] = {}


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _thread_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def _build_response(thread_id: str, graph_state) -> StateResponse:
    """
    Inspect a LangGraph state snapshot and return a normalised StateResponse.
    Only called when the graph is NOT in running/error state.
    """
    iteration_count = graph_state.values.get("iteration_count", 0)

    if graph_state.next:
        interrupts = [t.interrupts for t in graph_state.tasks if t.interrupts]
        if interrupts:
            data = interrupts[0][0].value
            payload = InterruptPayload(
                original_code=data.get("original_code", ""),
                refactored_code=data.get("refactored_code", ""),
                changes_summary=data.get("changes_summary", ""),
                analysis_report=data.get("analysis_report", []),
                security_report=data.get("security_report", []),
            )
            return StateResponse(
                thread_id=thread_id,
                stage="awaiting_review",
                iteration_count=iteration_count,
                interrupt_payload=payload,
            )

    # Graph finished — surface the final values
    values = graph_state.values
    result = ResultPayload(
        approved=values.get("approved", False),
        confidence_score=values.get("confidence_score", 0.0),
        iteration_count=values.get("iteration_count", 0),
        refactored_code=values.get("refactored_code", ""),
        changes_summary=values.get("changes_summary", ""),
        analysis_report=values.get("analysis_report", []),
        security_report=values.get("security_report", []),
        review_feedback=values.get("review_feedback", ""),
    )
    return StateResponse(
        thread_id=thread_id,
        stage="complete",
        iteration_count=iteration_count,
        result=result,
    )


async def _run_and_track(coro, thread_id: str) -> None:
    """
    Background task wrapper. Awaits the graph coroutine, then removes the
    'running' marker so subsequent get_state calls read from the checkpoint.
    Sets 'error' state if an exception is raised.
    """
    try:
        await coro
        _sessions.pop(thread_id, None)  # success — let get_state hit LangGraph
    except Exception as exc:
        _sessions[thread_id] = ("error", str(exc))


async def start_review(code: str, max_iterations: int) -> StateResponse:
    """
    Create a new review session and immediately return { stage: 'running' }.
    The pipeline runs in a background asyncio task.
    """
    graph = get_graph()
    thread_id = str(uuid.uuid4())
    config = _thread_config(thread_id)

    initial_state: ReviewState = {
        "original_code": code,
        "analysis_report": [],
        "security_report": [],
        "refactored_code": "",
        "changes_summary": "",
        "human_approved": None,
        "human_feedback": None,
        "test_cases": "",
        "approved": False,
        "review_feedback": "",
        "confidence_score": 0.0,
        "iteration_count": 0,
        "max_iterations": max_iterations,
    }

    _sessions[thread_id] = ("running", None)
    asyncio.create_task(
        _run_and_track(graph.ainvoke(initial_state, config=config), thread_id)
    )

    return StateResponse(thread_id=thread_id, stage="running", iteration_count=0)


async def get_state(thread_id: str) -> StateResponse:
    """
    Return the current state of a session.
    - 'running' / 'error' come from the in-memory tracker.
    - 'awaiting_review' / 'complete' come from the LangGraph checkpoint.
    """
    session = _sessions.get(thread_id)
    if session is not None:
        stage, error_msg = session
        return StateResponse(
            thread_id=thread_id,
            stage=stage,
            iteration_count=0,
            error=error_msg,
        )

    graph = get_graph()
    config = _thread_config(thread_id)
    graph_state = await graph.aget_state(config)
    return _build_response(thread_id, graph_state)


async def submit_decision(
    thread_id: str, approved: bool, feedback: str | None
) -> StateResponse:
    """
    Resume the graph from the human_review interrupt and immediately return
    { stage: 'running' }. The resumed pipeline runs in a background task.
    """
    graph = get_graph()
    config = _thread_config(thread_id)

    _sessions[thread_id] = ("running", None)
    asyncio.create_task(
        _run_and_track(
            graph.ainvoke(
                Command(resume={
                    "approved": approved,
                    "feedback": feedback if not approved else None,
                }),
                config=config,
            ),
            thread_id,
        )
    )

    return StateResponse(thread_id=thread_id, stage="running", iteration_count=0)
