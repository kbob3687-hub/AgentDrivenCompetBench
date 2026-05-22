<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vue.js&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-0.2+-orange?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PC9zdmc+" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/Status-WIP-yellow" />
</p>

# AgentDrivenCompetBench

> Multi-Agent 驱动的竞品分析系统 —— 从数据采集到报告生成，全链路自动化

<p align="center">
  <img src="docs/architecture.png" alt="System Architecture" width="720" />
</p>

## Overview

AgentDrivenCompetBench 是一个基于 LangGraph 的多智能体竞品分析平台。系统通过 4 个专业化 Agent 协作，自动完成竞品数据采集、结构化分析、报告撰写和质量审核，并支持 QA 反馈驱动的迭代优化闭环。

**核心场景：** 项目管理 SaaS 赛道竞品分析（Notion / 飞书 / ClickUp）

---

## Features

- **4-Agent Pipeline** — Collector → Analyst → Writer → QA，各司其职
- **QA 反馈闭环** — QA 检测到缺失维度时自动路由回 Collector 补充采集（最多 3 轮迭代）
- **实时可视化** — Vue 3 前端通过 SSE 实时展示 DAG 执行状态、Agent 日志和迭代进度
- **双 LLM 路由** — Claude 用于高质量推理，DeepSeek 用于高性价比提取任务
- **全链路可追溯** — 每条结论携带 SourceReference（URL + 原文片段 + 快照哈希），Langfuse 记录完整调用链
- **行业模板热插拔** — 通过 IndustryTemplate 扩展不同行业的分析维度

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Vue 3 Frontend                           │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌─────────────┐  │
│  │ DAG View │ │LogStream │ │IterTimeline│ │ResultPanel  │  │
│  └──────────┘ └──────────┘ └────────────┘ └─────────────┘  │
└────────────────────────┬────────────────────────────────────┘
                         │ SSE
┌────────────────────────▼────────────────────────────────────┐
│                   FastAPI Backend                             │
│  POST /api/analyze  │  GET /api/analyze/{id}/stream          │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│               LangGraph Orchestrator                          │
│                                                              │
│  ┌───────────┐    ┌──────────┐    ┌────────┐    ┌────┐     │
│  │ Collector │───▶│ Analyst  │───▶│ Writer │───▶│ QA │     │
│  └───────────┘    └──────────┘    └────────┘    └──┬─┘     │
│       ▲                                            │        │
│       └────────────── revise ◀─────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
         │                    │                │
    ┌────▼────┐         ┌────▼────┐     ┌────▼────┐
    │Jina/Play│         │Claude/DS│     │Langfuse │
    │wright   │         │  LLMs   │     │  Trace  │
    └─────────┘         └─────────┘     └─────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | LangGraph (StateGraph + conditional edges) |
| LLM | Claude (Anthropic) + DeepSeek (OpenAI-compatible) |
| Backend | FastAPI + Uvicorn + SSE |
| Frontend | Vue 3 + Vite + Tailwind CSS + Vue Flow |
| Data Scraping | Jina Reader + Playwright (fallback) |
| Observability | Langfuse v4 (trace → span → generation) |
| Storage | PostgreSQL 16 + Qdrant + Redis |
| Validation | Pydantic v2 structured output |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose
- API Keys: Anthropic / DeepSeek / Langfuse

### 1. Clone & Configure

```bash
git clone https://github.com/kbob3687-hub/AgentDrivenCompetBench.git
cd AgentDrivenCompetBench

cp .env.example .env
# 编辑 .env 填入你的 API Keys
```

### 2. Start Infrastructure

```bash
docker compose up -d
```

### 3. Run Backend

```bash
pip install -e ".[dev]"
uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000
```

### 4. Run Frontend

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 开始使用。

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/analyze` | 创建分析任务 |
| `GET` | `/api/analyze/{task_id}` | 查询任务状态与结果 |
| `GET` | `/api/analyze/{task_id}/stream` | SSE 实时事件流 |

### POST /api/analyze

```json
{
  "competitor_name": "Notion",
  "dimensions": ["pricing", "features", "integrations", "ai_capabilities"],
  "max_iterations": 3
}
```

### SSE Event Types

| Event | Description |
|-------|-------------|
| `agent_start` / `agent_end` | Agent 生命周期 |
| `sub_agent_start` / `sub_agent_end` | 子任务（并行采集）状态 |
| `log` | Agent 运行日志 |
| `qa_verdict` | QA 评审结果（pass / revise / reject） |
| `iteration_summary` | 迭代轮次摘要 |
| `complete` | 任务完成 |
| `error` | 错误信息 |

---

## Project Structure

```
├── src/
│   ├── agents/
│   │   ├── base.py              # BaseAgent 抽象基类
│   │   ├── collector/           # 数据采集 Agent
│   │   ├── analyst/             # 结构化分析 Agent
│   │   ├── writer/              # 报告生成 Agent
│   │   └── qa/                  # 质量审核 Agent
│   ├── orchestrator/            # LangGraph DAG 编排
│   ├── schemas/                 # Pydantic 数据模型
│   └── api/                     # FastAPI 服务
├── frontend/                    # Vue 3 前端
├── scripts/                     # 测试脚本
├── output/                      # 生成的报告
├── docker-compose.yml           # 基础设施
└── pyproject.toml               # 项目配置
```

---

## Agent Details

### Collector Agent
网页数据采集，支持 Jina Reader（轻量快速）和 Playwright（JS 渲染页面）双通道。并行 fan-out 抓取多个数据源，通过 LLM 提取结构化 claims。

### Analyst Agent
将原始 claims 按维度聚合，调用 LLM 生成结构化 `CompetitorProfile`（功能树、定价模型、SWOT、用户画像）。

### Writer Agent
将 CompetitorProfile 转化为带脚注引用的 Markdown 分析报告。

### QA Agent
双阶段质量审核：
1. **规则校验** — Schema 完整性、来源覆盖率、置信度阈值、维度覆盖
2. **LLM 语义审核** — 逻辑一致性、论据充分性

输出裁决：`pass` | `revise`（附缺失维度，路由回 Collector）| `reject`

---

## Development

```bash
# Lint & Format
ruff check src/ --fix
ruff format src/

# Run tests
pytest tests/ -v

# Test individual agents
python scripts/test_collector.py
python scripts/test_pipeline.py
python scripts/test_revise_scenario.py
```

---

## Roadmap

- [x] 4-Agent Pipeline (Collector → Analyst → Writer → QA)
- [x] LangGraph 编排 + QA 反馈闭环
- [x] FastAPI + SSE 实时流式接口
- [x] Vue 3 前端 DAG 可视化
- [x] Langfuse 全链路追踪
- [ ] 向量检索增强（Qdrant RAG）
- [ ] 多竞品对比分析
- [ ] 历史报告版本对比
- [ ] 用户自定义分析模板
- [ ] 导出 PDF / PPT

---

## License

MIT

---

<p align="center">
  <sub>Built with LangGraph + Claude + Vue 3</sub>
</p>
