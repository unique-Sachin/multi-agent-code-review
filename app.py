import time
import json
import os
import requests
import streamlit as st

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Code Review Agent",
    page_icon="🔍",
    layout="wide",
)

# ── API helpers ───────────────────────────────────────────────────────────────

def api_start(code: str, max_iterations: int) -> dict:
    resp = requests.post(
        f"{BASE_URL}/api/review/start",
        json={"code": code, "max_iterations": max_iterations},
    )
    resp.raise_for_status()
    return resp.json()


def api_get_state(thread_id: str) -> dict:
    resp = requests.get(f"{BASE_URL}/api/review/{thread_id}/state")
    resp.raise_for_status()
    return resp.json()


def api_decision(thread_id: str, approved: bool, feedback: str | None) -> dict:
    resp = requests.post(
        f"{BASE_URL}/api/review/{thread_id}/decision",
        json={"approved": approved, "feedback": feedback},
    )
    resp.raise_for_status()
    return resp.json()


def poll_until_ready(thread_id: str, poll_interval: float = 2.0, timeout: int = 180) -> dict:
    """Poll GET /state until stage is no longer 'running'. Returns the final state dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = api_get_state(thread_id)
        if data["stage"] != "running":
            return data
        time.sleep(poll_interval)
    raise TimeoutError(f"Pipeline timed out after {timeout}s")


def apply_state(data: dict):
    """Write an API state response into Streamlit session state."""
    stage = data["stage"]
    st.session_state.iteration_count = data.get("iteration_count", 0)
    if stage == "awaiting_review":
        st.session_state.interrupt_payload = data.get("interrupt_payload") or {}
        st.session_state.stage = "awaiting_review"
    elif stage == "complete":
        st.session_state.result = data.get("result") or {}
        st.session_state.stage = "complete"
    elif stage == "error":
        st.session_state.error_message = data.get("error", "Unknown error")
        st.session_state.stage = "error"


# ── Session state defaults ────────────────────────────────────────────────────

def init_session():
    defaults = {
        "stage": "input",       # input | awaiting_review | complete | error
        "thread_id": None,
        "interrupt_payload": None,
        "result": None,
        "iteration_count": 0,
        "error_message": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session()

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔍 Code Review")
    st.caption("Multi-Agent · LangGraph")
    st.divider()

    stage_labels = {
        "input": "⬜ Waiting for input",
        "awaiting_review": "🟡 Awaiting human review",
        "complete": "🟢 Complete",
        "error": "🔴 Error",
    }
    st.write("**Status**")
    st.write(stage_labels.get(st.session_state.stage, ""))

    if st.session_state.stage != "input" and st.session_state.thread_id:
        st.divider()
        st.metric("Iterations", st.session_state.iteration_count)
        st.caption(f"Thread `{st.session_state.thread_id[:8]}…`")

    if st.session_state.stage in ("awaiting_review", "complete", "error"):
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
        try:
            with st.spinner("Starting review pipeline…"):
                start_data = api_start(code_input.strip(), max_iter)
                st.session_state.thread_id = start_data["thread_id"]
            with st.spinner("Running analysis, security scan, and refactor in parallel…"):
                final_data = poll_until_ready(st.session_state.thread_id)
            apply_state(final_data)
        except Exception as e:
            st.session_state.stage = "error"
            st.session_state.error_message = str(e)
        st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# STAGE 2 — Human Review
# ═════════════════════════════════════════════════════════════════════════════

elif st.session_state.stage == "awaiting_review":
    payload: dict = st.session_state.interrupt_payload or {}
    thread_id: str = st.session_state.thread_id

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
            try:
                with st.spinner("Resuming pipeline…"):
                    api_decision(thread_id, approved=True, feedback=None)
                with st.spinner("Reviewer is checking the refactored code…"):
                    final_data = poll_until_ready(thread_id)
                apply_state(final_data)
            except Exception as e:
                st.session_state.stage = "error"
                st.session_state.error_message = str(e)
            st.rerun()

    with col_reject:
        reject_disabled = not (feedback_text or "").strip()
        if st.button(
            "❌ Reject & Re-refactor",
            use_container_width=True,
            disabled=reject_disabled,
        ):
            try:
                with st.spinner("Sending feedback and re-running refactor…"):
                    api_decision(thread_id, approved=False, feedback=feedback_text.strip())
                with st.spinner("Refactoring in progress…"):
                    final_data = poll_until_ready(thread_id)
                apply_state(final_data)
            except Exception as e:
                st.session_state.stage = "error"
                st.session_state.error_message = str(e)
            st.rerun()

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
        st.success(f"✅ Review complete — approved with {confidence} confidence")
    else:
        st.warning("⚠️ Review complete — max iterations reached without full approval")

    st.title("Final Result")

    # ── Metrics ───────────────────────────────────────────────────────────────
    m1, m2, m3 = st.columns(3)
    m1.metric("Confidence Score", f"{confidence}")
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

# ═════════════════════════════════════════════════════════════════════════════
# STAGE ERROR
# ═════════════════════════════════════════════════════════════════════════════

elif st.session_state.stage == "error":
    st.error(f"🔴 Pipeline error: {st.session_state.error_message}")
    st.caption("Use the **🔄 New Review** button in the sidebar to start again.")
