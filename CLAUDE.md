# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgentDrivenCompetBench — a LangGraph-based multi-agent competitive analysis system. Four specialized agents (Collector → Analyst → Writer → QA) collaborate to automate data collection, structured analysis, report generation, and quality review, with a QA feedback loop that routes back to the Collector for missing dimensions.

Target scenario: Project management SaaS (Notion / Feishu / ClickUp).

## Build & Run Commands

```bash
# Install dependencies (editable mode with dev extras)
pip install -e ".[dev]"

# Start infrastructure (PostgreSQL + Qdrant)
docker compose up -d

# Run backend
uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000

# Run frontend
cd frontend && npm install && npm run dev

# Lint & format
ruff check src/ --fix
ruff format src/

# Run tests
pytest tests/ -v

# Test individual agents
python scripts/test_collector.py
python scripts/test_pipeline.py
```

## Environment Setup

Copy `.env.example` to `.env`. Required API keys: `ANTHROPIC_API_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`. Database defaults assume local Docker containers.

## Architecture

### Agent Pipeline (LangGraph StateGraph)

```
Collector → Analyst → Writer → QA
                ↑                  │
                └── revise ────────┘
                                   │
              END ←──── pass ──────┘
```

- **Graph definition**: `src/orchestrator/graph.py` — `build_graph()` assembles the StateGraph
- **State**: `src/orchestrator/state.py` — `GraphState` (TypedDict) is the shared state container all nodes read/write
- **Nodes**: `src/orchestrator/nodes.py` — each node wraps an Agent, converting `GraphState` ↔ `AgentMessage`
- **Routing**: `src/orchestrator/edges.py` — `qa_routing()` decides: pass→END, revise→collector, reject→END
- **SSE variant**: `src/api/runner.py` — duplicate node implementations that publish SSE events during execution

### Two Graph Implementations

The codebase has **two parallel graph builds**:
1. `orchestrator/graph.py:build_graph()` — standalone, no SSE (used via `run_pipeline()`)
2. `api/runner.py:build_sse_graph()` — identical topology but nodes publish events to `event_bus` for frontend streaming

Both use the same `GraphState`, `qa_routing`, and Agent classes. When modifying node logic, update **both** files.

### Agent Architecture

All agents inherit `src/agents/base.py:BaseAgent`:
- `execute()` — entry point with Langfuse tracing + retry (max 3 attempts)
- `call_llm()` — routes to Anthropic Claude or OpenAI-compatible (DeepSeek) based on `AgentConfig.provider`
- `run()` — abstract, each agent implements its core logic
- Langfuse integration: trace → span → generation hierarchy, auto-flushed

Each agent has its own subpackage under `src/agents/` with `agent.py`, `prompts.py`, and optionally `tools.py` or `validators.py`.

### Dual LLM Routing

- `provider="anthropic"` → uses `anthropic.AsyncAnthropic` (Claude)
- `provider="openai_compat"` → uses `openai.AsyncOpenAI` (DeepSeek)
- Thinking models (`"thinking"` in model name) auto-enable extended thinking with budget, skip temperature

### Data Flow

1. **API**: `POST /api/analyze` creates a task, returns `task_id`
2. **Runner**: `api/runner.py:run_analysis()` builds the SSE graph, invokes with initial `GraphState`
3. **Collector**: fan-out parallel fetch (4 concurrent) via Jina Reader, LLM extracts `EvidencedClaim` objects
4. **Analyst**: aggregates claims into `CompetitorProfile` (Pydantic model in `src/schemas/competitor.py`)
5. **Writer**: profile → Markdown report with footnote references
6. **QA**: rule-based validators + LLM semantic review → verdict (pass/revise/reject)
7. **SSE**: `GET /api/analyze/{task_id}/stream` pushes real-time events

### Key Schemas (Pydantic v2)

- `src/schemas/competitor.py` — `CompetitorProfile` (the core output), `EvidencedClaim` (traceability atom), `FeatureNode`, `PricingModel`, `SWOTItem`, `UserPersona`
- `src/schemas/message.py` — `AgentMessage` (function-calling style inter-agent protocol), `MessageContext`, request/response models
- `src/schemas/trace.py` — `TraceSpan`, `FeedbackRecord`

### SSE Event System

`src/api/events.py` — `EventBus` class with per-task `asyncio.Queue`. Events: `agent_start`, `agent_end`, `sub_agent_start`, `sub_agent_end`, `log`, `qa_verdict`, `iteration_summary`, `complete`, `error`.

### Frontend (Vue 3 + Vite + Tailwind)

Located in `frontend/`. Key components:
- `DagView.vue` — renders the agent pipeline DAG
- `LogStream.vue` — real-time agent log display
- `IterationTimeline.vue` — QA feedback loop progress
- `ResultPanel.vue` — final report display
- Composables: `useSSE.ts` (SSE connection), `useAnalysis.ts` (API interaction)

## Development Notes

- Python 3.11+ required, Ruff line-length=100
- `pytest-asyncio` with `asyncio_mode = "auto"` — async tests just need `async def`
- The `.env` file is loaded by `dotenv` in `src/api/app.py` at startup
- Langfuse Cloud (not local Docker) is used for tracing — configure keys in `.env`
- Package root is `src/` (setuptools `package-dir = {"" = "src"}`)
