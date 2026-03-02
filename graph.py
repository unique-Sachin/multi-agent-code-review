from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from state import ReviewState
from agents import (
    analyzer_agent,
    security_agent,
    refactor_agent,
    human_review_node,
    test_generator_agent,
    reviewer_agent
)

def start_node(state: ReviewState):
    return state

def build_graph():

    workflow = StateGraph(ReviewState)

    # Add Nodes
    workflow.add_node("start", start_node)
    workflow.add_node("analyzer", analyzer_agent)
    workflow.add_node("security", security_agent)
    workflow.add_node("refactor", refactor_agent)
    workflow.add_node("human_review", human_review_node)
    # workflow.add_node("test_generator", test_generator_agent)
    workflow.add_node("reviewer", reviewer_agent)

    workflow.set_entry_point("start")

    # FAN OUT (parallel execution)
    workflow.add_edge("start", "analyzer")
    workflow.add_edge("start", "security")

    # FAN IN — both branches must complete before refactor runs.
    workflow.add_edge("analyzer", "refactor")
    workflow.add_edge("security", "refactor")

    workflow.add_edge("refactor", "human_review")

    workflow.add_conditional_edges(
        "human_review",
        human_router,
        {
            "approve": "reviewer",
            "reject": "refactor"
        }
    )

    # workflow.add_edge("test_generator", "reviewer")

    workflow.add_conditional_edges(
        "reviewer",
        reviewer_router,
        {
            "approve": END,
            "retry": "refactor",
            "stop": END
        }
    )

    # MemorySaver checkpointer is required for interrupt() to persist state
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


# ---------- Routers ----------

def human_router(state: ReviewState):
    if state["human_approved"]:
        return "approve"
    return "reject"


def reviewer_router(state: ReviewState):
    if state["approved"]:
        return "approve"

    if state["iteration_count"] >= state["max_iterations"]:
        return "stop"

    return "retry"