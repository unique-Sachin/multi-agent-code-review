# Code Review Agent

An automated code review pipeline built with **LangGraph** and **GPT-4o-mini**. Multiple specialised AI agents analyse, secure, and refactor your code in parallel, with a human-in-the-loop approval step before finalisation.

---

## How It Works

The pipeline follows a fan-out / fan-in graph pattern:

```
              ┌─────────────┐
              │    start    │
              └──────┬──────┘
          ┌──────────┴──────────┐
          ▼                     ▼
    [analyzer]             [security] (Toolcall - Bandit static security suite)        ← parallel
          └──────────┬──────────┘
                     ▼
                [refactor]
                     │
                     ▼
              [human_review]  ◄── INTERRUPT (waits for your input)
                  /     \
            approve      reject (with feedback)
               │                │
               │                ▼
               │           [refactor]  ← loop
               ▼                
          [reviewer]        
           /     │    \
          /      │     \
         /       │      \
        /        │       stop (max iterations)
       /         │        
    approve    retry (with feedback)
       │          │
       │     [refactor] ← loop  
       │
      END
```

---

## Agents

| Agent | Role |
|---|---|
| `analyzer_agent` | Detects code smells, readability issues, and performance concerns |
| `security_agent` | Scans for SQL injection, hardcoded secrets, unsafe `eval`/`exec`, and insecure deserialization |
| `refactor_agent` | Rewrites the code to fix all reported issues; incorporates human feedback on rejection |
| `human_review_node` | Pauses the graph (LangGraph interrupt) and waits for human approval or rejection |
| `reviewer_agent` | Final quality gate — approves the refactor with a confidence score or triggers a retry |
| `test_generator_agent` | *(Included but currently disabled)* Generates unit tests for the refactored code |

---

## Project Structure

```
multi-agent-code-review/
├── app.py            # Streamlit web UI (3-stage: input → review → complete)
├── main.py           # CLI runner (terminal-based alternative)
├── graph.py          # LangGraph StateGraph definition and routers
├── agents.py         # All agent functions
├── state.py          # ReviewState TypedDict with parallel-merge reducers
├── models.py         # Pydantic output models for structured LLM responses
├── llm.py            # LLM initialisation (GPT-4o-mini via LangChain)
└── requirements.txt  # Python dependencies
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-...
```

---

## Running the App

### Streamlit UI (recommended)

```bash
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

**Workflow in the UI:**
1. Paste your code and set the max retry iterations.
2. Click **Start Review** — analysis, security scan, and refactoring run in parallel.
3. Review the side-by-side diff, quality issues, and security findings.
4. **Approve** to finalize, or **Reject** with feedback to trigger another refactor cycle.
5. Download the final `output.json` result.

### CLI Runner

```bash
python main.py
```

Runs the same pipeline in the terminal with interactive prompts for human review.

---

## Key Concepts

- **Parallel fan-out**: `analyzer` and `security` agents run simultaneously; their results are merged into the state via `operator.add` reducers before `refactor` begins.
- **Human-in-the-loop**: LangGraph's `interrupt()` suspends graph execution, preserving full state in a `MemorySaver` checkpoint until the human responds.
- **Retry loop**: If the human rejects or the `reviewer_agent` is not satisfied, the graph loops back to `refactor` (up to `max_iterations` times) before stopping.
- **Structured outputs**: All agents use Pydantic models (`AnalysisOutput`, `SecurityOutput`, `RefactorOutput`, `ReviewOutput`) for reliable, typed LLM responses.

---

## Dependencies

| Package | Purpose |
|---|---|
| `langgraph` | Agent graph orchestration and interrupt/resume |
| `langchain-openai` | GPT-4o-mini integration |
| `openai` | OpenAI SDK |
| `pydantic` | Structured output models |
| `streamlit` | Web UI |
| `python-dotenv` | Environment variable loading |
| `langsmith` | LangChain tracing/observability |

## Summary Flow for a Client

Client                          FastAPI                        LangGraph
  │                                │                               │
  │── POST /reviews ──────────────►│── ainvoke (background) ──────►│
  │◄── { thread_id } ─────────────│                               │ (running)
  │                                │                               │
  │── GET /stream ────────────────►│◄── aget_state ───────────────│
  │◄── { stage: "awaiting_review"} │                               │ (interrupted)
  │                                │                               │
  │── GET /interrupt ─────────────►│  (reads interrupt payload)    │
  │◄── { refactored_code, ... } ───│                               │
  │                                │                               │
  │── POST /resume ───────────────►│── ainvoke(Command(resume)) ──►│
  │◄── { stage: "running" } ───────│                               │ (resuming)
  │                                │                               │
  │── GET /stream ────────────────►│◄── aget_state ───────────────│
  │◄── { stage: "complete" } ──────│                               │ (done)
  │                                │                               │
  │── GET /result ─────────────────►│  (reads final values)        │
  │◄── { refactored_code, ... } ───│                               │



  ## SSE Flow 
Client opens GET /reviews/{id}/stream  →  waits (connection held open)
                                                    │
Background task hits interrupt  ─────────────────► queue.put("interrupt")
                                                    │
SSE pushes to client immediately  ◄─────────────────┘
Client renders review UI, user decides
Client sends POST /reviews/{id}/resume
                                                    │
Background task finishes  ───────────────────────► queue.put("complete")
                                                    │
SSE pushes final result to client  ◄────────────────┘
Connection closes