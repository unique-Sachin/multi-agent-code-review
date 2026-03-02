from dotenv import load_dotenv
load_dotenv()

from graph import build_graph
from state import ReviewState
from langgraph.types import Command
from langchain_core.runnables import RunnableConfig
import asyncio
import json


async def main():
    app = build_graph()

    thread_config: RunnableConfig = {"configurable": {"thread_id": "review-session-1"}}

    initial_state: ReviewState = {
        "original_code": """def process(data):
    if data:
        if isinstance(data, dict):
            if "value" in data:
                if data["value"] > 0:
                    print("Valid")
                else:
                    print("Invalid")""",
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
        "max_iterations": 3
    }

    # ── First run: executes until the human_review interrupt ──────────────────
    result = await app.ainvoke(initial_state, config=thread_config)

    # ── Interrupt / resume loop ───────────────────────────────────────────────
    while True:
        graph_state = await app.aget_state(thread_config)

        if not graph_state.next:
            break

        interrupts = [
            task.interrupts
            for task in graph_state.tasks
            if task.interrupts
        ]
        if not interrupts:
            break

        payload = interrupts[0][0].value  # first interrupt's value dict

        print("\n" + "=" * 60)
        print("HUMAN REVIEW REQUIRED")
        print("=" * 60)
        print("\n--- Changes Summary ---")
        print(payload.get("changes_summary", ""))
        print("\n--- Original Code ---")
        print(payload.get("original_code", ""))
        print("\n--- Refactored Code ---")
        print(payload.get("refactored_code", ""))
        print("\n--- Analysis Report ---")
        for issue in payload.get("analysis_report", []):
            print(f"  • {issue}")
        print("\n--- Security Report ---")
        for vuln in payload.get("security_report", []):
            print(f"  • {vuln}")

        decision = input("\nApprove refactor? (yes/no): ").strip().lower()
        feedback: str | None = None
        if decision != "yes":
            feedback = input("Enter feedback for the refactor agent: ").strip() or None

        # Resume the graph with the human's decision
        result = await app.ainvoke(
            Command(resume={"approved": decision == "yes", "feedback": feedback}),
            config=thread_config
        )

    # ── Persist final state ───────────────────────────────────────────────────
    with open("output.json", "w") as f:
        json.dump(result, f, indent=2)

    print("\n✓ Review complete. Final result written to output.json")


if __name__ == "__main__":
    asyncio.run(main())