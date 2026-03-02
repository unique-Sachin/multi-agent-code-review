from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import asyncio
import json
import uuid
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from graph import build_graph
from state import ReviewState

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Multi-Agent Code Review",
    page_icon="🔍",
    layout="wide",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

@st.cache_resource
def get_app():
    """Build and cache the compiled LangGraph app across all reruns."""
    return build_graph()


def run_async(coro):
    return asyncio.run(coro)


def thread_config() -> RunnableConfig:
    return {"configurable": {"thread_id": st.session_state.thread_id}}


def finish_after_resume():
    """
    After resuming from an interrupt, check if the graph paused again
    (another review cycle) or finished. Update session state accordingly.
    """
    graph_state = run_async(app.aget_state(thread_config()))

    if graph_state.next:
        interrupts = [t.interrupts for t in graph_state.tasks if t.interrupts]
        if interrupts:
            st.session_state.interrupt_payload = interrupts[0][0].value
            st.session_state.iteration_count = graph_state.values.get("iteration_count", 0)
            st.session_state.stage = "awaiting_review"
        else:
            st.session_state.result = graph_state.values
            st.session_state.stage = "complete"
    else:
        st.session_state.result = graph_state.values
        st.session_state.stage = "complete"

    st.rerun()


# ── Session state defaults ────────────────────────────────────────────────────

def init_session():
    defaults = {
        "stage": "input",       # input | awaiting_review | complete
        "thread_id": str(uuid.uuid4()),
        "interrupt_payload": None,
        "result": None,
        "iteration_count": 0,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session()
app = get_app()

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔍 Code Review")
    st.caption("Multi-Agent · LangGraph")
    st.divider()

    stage_labels = {
        "input": "⬜ Waiting for input",
        "awaiting_review": "🟡 Awaiting human review",
        "complete": "🟢 Complete",
    }
    st.write("**Status**")
    st.write(stage_labels.get(st.session_state.stage, ""))

    if st.session_state.stage != "input":
        st.divider()
        st.metric("Iterations", st.session_state.iteration_count)
        st.caption(f"Thread `{st.session_state.thread_id[:8]}…`")

    if st.session_state.stage in ("awaiting_review", "complete"):
        st.divider()
        if st.button("🔄 New Review", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# STAGE 1 — Code Input
# ═════════════════════════════════════════════════════════════════════════════

if st.session_state.stage == "input":
    st.title("Multi-Agent Code Review")
    st.write(
        "Paste your code below. The pipeline will run **analysis**, **security scan**, "
        "and **refactoring** in parallel, then pause for your approval before finalising."
    )

    code_input = st.text_area(
        "Code to review",
        height=320,
        placeholder="Paste your code here…",
    )

    max_iter = st.slider("Max auto-retry iterations (reviewer → refactor loop)", 1, 5, 2)

    st.button(
        "🚀 Start Review",
        type="primary",
        disabled=not (code_input or "").strip(),
        key="start_btn",
    )

    if st.session_state.get("start_btn") and code_input.strip():
        initial_state: ReviewState = {
            "original_code": code_input.strip(),
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
            "max_iterations": max_iter,
        }

        with st.spinner("Running analysis, security scan, and refactor in parallel…"):
            run_async(app.ainvoke(initial_state, config=thread_config()))

        graph_state = run_async(app.aget_state(thread_config()))

        if graph_state.next:
            interrupts = [t.interrupts for t in graph_state.tasks if t.interrupts]
            if interrupts:
                st.session_state.interrupt_payload = interrupts[0][0].value
                st.session_state.iteration_count = graph_state.values.get("iteration_count", 0)
                st.session_state.stage = "awaiting_review"
            else:
                st.session_state.result = graph_state.values
                st.session_state.stage = "complete"
        else:
            st.session_state.result = graph_state.values
            st.session_state.stage = "complete"

        st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# STAGE 2 — Human Review
# ═════════════════════════════════════════════════════════════════════════════

elif st.session_state.stage == "awaiting_review":
    payload: dict = st.session_state.interrupt_payload or {}

    st.title("👤 Human Review")
    st.info(
        "The agents have completed analysis and refactoring. "
        "Review the output, then **approve** or **reject with feedback**.",
        icon="ℹ️",
    )

    # ── Changes summary ───────────────────────────────────────────────────────
    with st.expander("📋 Changes Summary", expanded=True):
        summary = payload.get("changes_summary", "")
        st.write(summary if summary else "_No summary provided._")

    # ── Side-by-side code ─────────────────────────────────────────────────────
    col_orig, col_new = st.columns(2)
    with col_orig:
        st.subheader("Original Code")
        st.code(payload.get("original_code", ""), language="python")
    with col_new:
        st.subheader("Refactored Code")
        st.code(payload.get("refactored_code", ""), language="python")

    # ── Reports ───────────────────────────────────────────────────────────────
    col_analysis, col_security = st.columns(2)
    with col_analysis:
        with st.expander("🔎 Code Quality Issues", expanded=True):
            issues = payload.get("analysis_report", [])
            if issues:
                for issue in issues:
                    st.warning(issue, icon="⚠️")
            else:
                st.success("No quality issues found.")
    with col_security:
        with st.expander("🔒 Security Issues", expanded=True):
            vulns = payload.get("security_report", [])
            if vulns:
                for vuln in vulns:
                    st.error(vuln, icon="🚨")
            else:
                st.success("No security vulnerabilities found.")

    st.divider()

    # ── Decision ──────────────────────────────────────────────────────────────
    st.subheader("Your Decision")

    feedback_text = st.text_area(
        "Feedback for refactor agent (required when rejecting)",
        placeholder="e.g. Use parameterised queries, avoid string concatenation for SQL…",
        key="feedback_input",
    )

    col_approve, col_reject = st.columns(2)

    with col_approve:
        if st.button("✅ Approve", type="primary", use_container_width=True):
            with st.spinner("Resuming pipeline…"):
                run_async(app.ainvoke(
                    Command(resume={"approved": True, "feedback": None}),
                    config=thread_config(),
                ))
            finish_after_resume()

    with col_reject:
        reject_disabled = not (feedback_text or "").strip()
        if st.button(
            "❌ Reject & Re-refactor",
            use_container_width=True,
            disabled=reject_disabled,
        ):
            with st.spinner("Sending feedback and re-running refactor…"):
                run_async(app.ainvoke(
                    Command(resume={"approved": False, "feedback": feedback_text.strip()}),
                    config=thread_config(),
                ))
            finish_after_resume()

    if reject_disabled:
        st.caption("Add feedback above to enable rejection.")

# ═════════════════════════════════════════════════════════════════════════════
# STAGE 3 — Complete
# ═════════════════════════════════════════════════════════════════════════════

elif st.session_state.stage == "complete":
    result: dict = st.session_state.result or {}

    approved = result.get("approved", False)
    confidence: float = result.get("confidence_score", 0.0)

    if approved:
        st.success(f"✅ Review complete — approved with {confidence:.0%} confidence")
    else:
        st.warning("⚠️ Review complete — max iterations reached without full approval")

    st.title("Final Result")

    # ── Metrics ───────────────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric("Confidence Score", f"{confidence:.0%}")
    m2.metric("Iterations Used", result.get("iteration_count", "—"))
    m3.metric("Status", "Approved ✅" if approved else "Stopped ⚠️")

    # ── Reviewer feedback ─────────────────────────────────────────────────────
    review_feedback = result.get("review_feedback", "")
    if review_feedback:
        with st.expander("📝 Reviewer Feedback", expanded=True):
            st.write(review_feedback)

    # ── Final refactored code ─────────────────────────────────────────────────
    st.subheader("Refactored Code")
    st.code(result.get("refactored_code", ""), language="python")

    # ── Reports ───────────────────────────────────────────────────────────────
    col_a, col_s = st.columns(2)
    with col_a:
        with st.expander("🔎 Analysis Report"):
            for issue in result.get("analysis_report", []):
                st.write(f"- {issue}")
    with col_s:
        with st.expander("🔒 Security Report"):
            for vuln in result.get("security_report", []):
                st.write(f"- {vuln}")

    st.divider()

    # ── Download ──────────────────────────────────────────────────────────────
    st.download_button(
        label="⬇️ Download output.json",
        data=json.dumps(result, indent=2),
        file_name="output.json",
        mime="application/json",
    )
