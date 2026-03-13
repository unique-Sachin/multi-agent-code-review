import asyncio
import uuid
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from langgraph.errors import GraphInterrupt

from state import ReviewState
from api.schemas.review import (
    StateResponse,
    InterruptPayload,
    ResultPayload,
    SessionHistoryItem,
)
from db import sessions as sessions_db
from db import history as history_db

_graph = None
_sessions_container = None
_history_container = None


def init(graph, sessions_container, history_container) -> None:
    """Called once from FastAPI lifespan to inject runtime dependencies."""
    global _graph, _sessions_container, _history_container
    _graph = graph
    _sessions_container = sessions_container
    _history_container = history_container


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
    Background task wrapper. Removes the transient running/error session record
    after the pipeline finishes and writes the final status to review_history.
    """
    try:
        await coro
        await sessions_db.delete_session(_sessions_container, thread_id)

        config = _thread_config(thread_id)
        graph_state = await _graph.aget_state(config)
        response = _build_response(thread_id, graph_state)
        # Determine final status: awaiting_review (interrupt) or complete
        final_status = response.stage if response.stage in ("awaiting_review", "complete") else "complete"
        await history_db.update_history(_history_container, thread_id, final_status)
    except GraphInterrupt:
        await sessions_db.delete_session(_sessions_container, thread_id)
        await history_db.update_history(_history_container, thread_id, "awaiting_review")
    except Exception as exc:
        await sessions_db.upsert_session(_sessions_container, thread_id, "error", str(exc))
        await history_db.update_history(_history_container, thread_id, "error")


async def start_review(code: str, max_iterations: int) -> StateResponse:
    """
    Create a new review session and immediately return { stage: 'running' }.
    The pipeline runs in a background asyncio task.
    """
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

    await sessions_db.upsert_session(_sessions_container, thread_id, "running")
    await history_db.create_history(_history_container, thread_id, code)

    asyncio.create_task(
        _run_and_track(_graph.ainvoke(initial_state, config=config), thread_id)
    )

    return StateResponse(thread_id=thread_id, stage="running", iteration_count=0)


async def get_state(thread_id: str) -> StateResponse:
    """
    Return the current state of a session.
    - 'running' / 'error' are read from the Cosmos DB sessions container.
    - 'awaiting_review' / 'complete' are derived from the LangGraph checkpoint.
    """
    session = await sessions_db.get_session(_sessions_container, thread_id)
    if session is not None:
        return StateResponse(
            thread_id=thread_id,
            stage=session["stage"],
            iteration_count=0,
            error=session.get("error_msg"),
        )

    config = _thread_config(thread_id)
    graph_state = await _graph.aget_state(config)
    return _build_response(thread_id, graph_state)


async def submit_decision(
    thread_id: str, approved: bool, feedback: str | None
) -> StateResponse:
    """
    Resume the graph from the human_review interrupt and immediately return
    { stage: 'running' }. The resumed pipeline runs in a background task.
    """
    config = _thread_config(thread_id)

    await sessions_db.upsert_session(_sessions_container, thread_id, "running")
    await history_db.update_history(_history_container, thread_id, "running")

    asyncio.create_task(
        _run_and_track(
            _graph.ainvoke(
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


async def list_sessions(limit: int = 30) -> list[SessionHistoryItem]:
    docs = await history_db.list_history(_history_container, limit=limit)
    return [
        SessionHistoryItem(
            thread_id=doc.get("thread_id", ""),
            status=doc.get("status", "running"),
            code_preview=doc.get("code_preview", ""),
        )
        for doc in docs
    ]



