<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vue.js&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-0.2+-orange?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PC9zdmc+" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Tests-49_passed-brightgreen?logo=pytest&logoColor=white" />
  <img src="https://img.shields.io/badge/Langfuse-Traced-purple?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PC9zdmc+" />
</p>

# AgentDrivenCompetBench

> Multi-Agent 驱动的竞品分析系统 —— 从数据采集到报告生成，全链路自动化 + QA 反馈闭环迭代优化

<p align="center">
  <img src="docs/architecture.png" alt="System Architecture" width="720" />
</p>

## Highlights

| 能力 | 实现方式 | 状态 |
|------|---------|------|
| 4-Agent 协作 Pipeline | LangGraph StateGraph + conditional edges | ✅ |
| QA 反馈闭环 + 迭代对比 | QA→Collector 路由 + before/after delta 可视化 | ✅ |
| Fan-out 并行采集 | asyncio.Semaphore(4) + sub-agent SSE 追踪 | ✅ |
| 双 LLM 智能路由 | Claude (高质量推理) + DeepSeek (高性价比提取) | ✅ |
| 行业模板热插拔 | SaaS / 消费品 / 硬件 三套模板，运行时注入 | ✅ |
| Agent Trace 可观测面板 | 内嵌耗时/Token/成本统计 + Langfuse 一键跳转 | ✅ |
| 全链路溯源 | EvidencedClaim (URL + snippet + snapshot_hash) | ✅ |
| 实时 SSE 流式展示 | 9 种事件类型，前端 DAG/日志/进度同步更新 | ✅ |
| 测试覆盖 | 49 tests (validators / schemas / routing / fan-out) | ✅ |

---

## Demo

```
输入: "ClickUp" + 维度[pricing, features] + 行业模板[SaaS]
输出: 2500+ 字结构化报告 | 14-47 条溯源 claims | QA 评分 0.68-0.78
耗时: ~110s (4 agent 串行) | 预估成本: < $0.01/次 (DeepSeek)
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Vue 3 Frontend                            │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌───────────────┐   │
│  │ DAG View │ │LogStream │ │IterTimeline│ │ Agent Trace   │   │
│  │          │ │          │ │(delta对比) │ │(Token/Cost)   │   │
│  └──────────┘ └──────────┘ └────────────┘ └───────────────┘   │
└────────────────────────────┬────────────────────────────────────┘
                             │ SSE (9 event types)
┌────────────────────────────▼────────────────────────────────────┐
│                     FastAPI Backend                               │
│  POST /analyze  │  GET /stream  │  GET /templates                │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                 LangGraph StateGraph                              │
│                                                                  │
│  ┌───────────┐    ┌──────────┐    ┌────────┐    ┌────┐         │
│  │ Collector │───▶│ Analyst  │───▶│ Writer │───▶│ QA │         │
│  │(fan-out×4)│    │          │    │        │    │    │         │
│  └───────────┘    └──────────┘    └────────┘    └──┬─┘         │
│       ▲                                            │            │
│       └──────────── revise (missing dims) ─────────┘            │
│                                                    │            │
│                              pass/reject ──────────▶ END        │
└─────────────────────────────────────────────────────────────────┘
         │                    │                │
    ┌────▼────┐         ┌────▼────┐     ┌────▼────┐
    │Jina     │         │Claude   │     │Langfuse │
    │Reader   │         │DeepSeek │     │Cloud    │
    │+PW降级  │         │(双路由) │     │(Trace)  │
    └─────────┘         └─────────┘     └─────────┘
```

---

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Orchestration | LangGraph StateGraph | 声明式 DAG + conditional edges，天然支持循环 |
| LLM Routing | Claude + DeepSeek | 推理质量 vs 性价比，按任务类型路由 |
| Backend | FastAPI + SSE | 异步非阻塞 + 原生流式推送 |
| Frontend | Vue 3 + Vite + Tailwind + Vue Flow | 响应式 DAG 可视化 |
| Scraping | Jina Reader + Playwright fallback | 轻量优先，JS 渲染兜底 |
| Observability | Langfuse v4 | trace → span → generation 三层追踪 |
| Validation | Pydantic v2 | 结构化输出 + 运行时校验 |
| Testing | pytest + pytest-asyncio | 49 tests, 5s 全量通过 |

---

## Quick Start

### Prerequisites

- Python 3.11+ / Node.js 18+ / Docker
- API Keys: Anthropic + DeepSeek + Langfuse

### Setup

```bash
git clone https://github.com/kbob3687-hub/AgentDrivenCompetBench.git
cd AgentDrivenCompetBench

cp .env.example .env   # 填入 API Keys

pip install -e ".[dev]"
docker compose up -d   # PostgreSQL + Qdrant

# 启动后端
uvicorn src.api.app:app --host 0.0.0.0 --port 8001

# 启动前端
cd frontend && npm install && npm run dev
```

访问 http://localhost:5173 开始分析。

---

## Core Design

### 1. QA 反馈闭环 (Feedback Loop)

```
Iteration 1: score=0.52, verdict=revise, missing=[integrations]
     ↓ 自动路由回 Collector 补充采集
Iteration 2: score=0.76, verdict=pass ✓
     ↓
前端 IterationTimeline 展示 before/after delta: +24% ↑
```

QA Agent 采用双阶段审核：
- **规则校验**: 维度覆盖率、来源完整性、置信度阈值、Schema 一致性
- **LLM 语义审核**: 逻辑连贯性、论据充分性、事实准确性

### 2. Fan-out 并行采集

Collector 对每个 URL 启动独立 sub-agent，`asyncio.Semaphore(4)` 控制并发：

```
fetch-0: notion.so/pricing     ──┐
fetch-1: notion.so/product     ──┼── 并行执行，SSE 实时上报进度
fetch-2: notion.so/integrations──┘
```

每个 sub-agent 的生命周期通过 `sub_agent_start` / `sub_agent_end` 事件推送到前端。

### 3. 行业模板系统

```python
# 运行时注入行业特定维度
template = load_template("saas")  # → api_openness, integration_count, ai_features...
template = load_template("consumer")  # → brand_positioning, channel_strategy...
template = load_template("hardware")  # → supply_chain, certification...
```

模板字段自动注入 Collector 采集指令和 QA 覆盖度检查。

### 4. Agent Trace 可观测性

前端内嵌 Trace 面板，无需切换工具即可查看：
- 每个 Agent 的耗时、模型、Input/Output Token 数
- 预估成本（按 DeepSeek/Claude 分别计价）
- Prompt/Output 预览（前 200/300 字符）
- Langfuse 一键跳转查看完整调用链

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/analyze` | 创建分析任务 |
| `GET` | `/api/analyze/{task_id}` | 查询任务状态与结果 |
| `GET` | `/api/analyze/{task_id}/stream` | SSE 实时事件流 |
| `GET` | `/api/analyze/templates` | 列出可用行业模板 |
| `GET` | `/api/analyze/templates/{industry}` | 获取模板 Schema |

### Request Example

```json
{
  "competitor_name": "Notion",
  "dimensions": ["pricing", "features", "integrations"],
  "industry": "saas",
  "max_iterations": 3
}
```

### SSE Event Types

| Event | Payload | Description |
|-------|---------|-------------|
| `agent_start` | `{agent, iteration}` | Agent 开始执行 |
| `agent_end` | `{agent, iteration, duration_ms}` | Agent 执行完成 |
| `sub_agent_start` | `{parent, sub_id, url}` | 子采集任务启动 |
| `sub_agent_end` | `{sub_id, success, claims_count}` | 子采集任务完成 |
| `log` | `{message, agent}` | 运行日志 |
| `qa_verdict` | `{verdict, score, missing_dimensions}` | QA 评审结果 |
| `iteration_summary` | `{iteration, score, issues_count}` | 迭代轮次摘要 |
| `complete` | `{report_markdown, agent_traces, ...}` | 任务完成 |
| `error` | `{message}` | 错误信息 |

---

## Project Structure

```
src/
├── agents/
│   ├── base.py                 # BaseAgent (Langfuse tracing + retry + dual LLM)
│   ├── collector/              # 数据采集 (Jina Reader + Playwright + LLM extract)
│   ├── analyst/                # 结构化分析 (claims → CompetitorProfile)
│   ├── writer/                 # 报告生成 (profile → Markdown + footnotes)
│   └── qa/                     # 质量审核 (rule validators + LLM semantic review)
├── orchestrator/
│   ├── state.py                # GraphState (TypedDict, 共享状态容器)
│   ├── graph.py                # build_graph() 独立版
│   └── edges.py                # qa_routing() 条件路由
├── schemas/
│   ├── competitor.py           # CompetitorProfile, EvidencedClaim, FeatureNode...
│   ├── extensions.py           # IndustryTemplate 行业模板系统
│   └── message.py              # AgentMessage 函数调用协议
└── api/
    ├── app.py                  # FastAPI 入口
    ├── runner.py               # SSE 版 pipeline (event publishing + trace collection)
    ├── events.py               # EventBus (per-task asyncio.Queue)
    └── routes/analyze.py       # REST + SSE 路由

frontend/src/
├── components/
│   ├── DagView.vue             # Agent DAG 可视化 (Vue Flow)
│   ├── LogStream.vue           # 实时日志流
│   ├── IterationTimeline.vue   # QA 迭代进度 + before/after delta
│   ├── ResultPanel.vue         # 报告 + Agent Trace + 反馈历史
│   └── AnalysisForm.vue        # 输入表单 + 行业模板选择
├── composables/
│   ├── useSSE.ts               # SSE 连接管理
│   └── useAnalysis.ts          # 状态机 + 事件分发
└── types/index.ts              # TypeScript 类型定义

tests/
├── test_qa_validators.py       # 15 tests - QA 规则校验器
├── test_schemas.py             # 12 tests - 数据模型 + 行业模板
├── test_orchestrator.py        # 9 tests  - 图路由 + 状态结构
├── test_fan_out_subagent.py    # 11 tests - 并行采集模式
└── conftest.py                 # 共享 fixtures
```

---

## Testing

```bash
pytest tests/ -v          # 49 tests, ~5s
ruff check src/ --fix     # Lint
ruff format src/          # Format
```

测试覆盖：
- QA validators: 维度覆盖、来源校验、snippet 真实性、一致性检查、置信度阈值
- Schemas: EvidencedClaim 构造、行业模板加载/校验/列举
- Orchestrator: qa_routing 5 种路径、图结构验证、FeedbackRecord 序列化
- Fan-out: 并行执行、失败容错、Semaphore 并发控制、URL 生成

---

## Roadmap

- [x] 4-Agent Pipeline (Collector → Analyst → Writer → QA)
- [x] LangGraph StateGraph + QA 反馈闭环
- [x] FastAPI + SSE 实时流式接口
- [x] Vue 3 前端 DAG 可视化
- [x] Fan-out 并行采集 + sub-agent 追踪
- [x] 行业模板热插拔 (SaaS / Consumer / Hardware)
- [x] Agent Trace 可观测面板 + Langfuse 集成
- [x] QA 迭代 before/after delta 对比展示
- [x] 测试套件 (49 tests)
- [ ] 向量检索增强 (Qdrant RAG)
- [ ] 多竞品横向对比视图
- [ ] 导出 PDF / PPT

---

## License

MIT

---

<p align="center">
  <sub>Built with LangGraph + Claude + DeepSeek + Vue 3 | 多智能体协作 × 反馈闭环 × 全链路可观测</sub>
</p>
</content>
</invoke>