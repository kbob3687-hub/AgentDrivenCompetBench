"""StateGraph组装 - 串联五个Agent节点 + QA反馈循环

核心架构：
  Discovery → Collector → Analyst → Writer → QA
                  ↑           ↑           ↑     │
                  │           │           │     │
                  └───────────┴───────────┘     │
                   revise → 按问题类型路由       │
                                                │
  END ←──── pass ──────────────────────────────┘

QA反馈路由规则：
  - 数据问题（missing_source/factual_error/outdated）→ Collector
  - 分析问题（low_confidence/inconsistency）→ Analyst
  - 报告问题（schema_violation）→ Writer

Discovery节点（双路径）：
  - Warm Path: 已知竞品从缓存直接返回精确URL
  - Cold Path: 未知竞品通过Jina Search发现官网域名 + 构造维度URL

支持PostgresSaver做Checkpointer，实现断点续跑。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from time import perf_counter
from typing import Any

from langgraph.graph import END, StateGraph

from agents.base import execution_records
from orchestrator.edges import qa_routing
from orchestrator.nodes import analyst_node, collector_node, discovery_node, qa_node, writer_node
from orchestrator.state import GraphState


def _make_trace_id(seed: str | None = None) -> str:
    """生成Langfuse兼容的32字符hex trace_id"""
    raw = seed or uuid.uuid4().hex
    return hashlib.md5(raw.encode()).hexdigest()


def _observed_node(name: str, node: Any) -> Any:
    async def observed(state: GraphState) -> dict[str, Any]:
        records = execution_records.get()
        record = {
            "kind": "node",
            "agent": name,
            "iteration": state.get("iteration", 1),
            "status": "running",
        }
        if records is not None:
            records.append(record)
        started = perf_counter()
        try:
            update = await node(state)
            record["status"] = "error" if update.get("error") else "completed"
            # Preserve actual intermediate outputs, including partial results on failure.
            record["state_update"] = update
            return update
        except Exception as exc:
            record.update(status="error", error=f"{type(exc).__name__}: {exc}")
            raise
        finally:
            record["latency_seconds"] = perf_counter() - started
            if record["status"] == "running":
                record["status"] = "cancelled"

    return observed


def _continue_unless_failed(state: GraphState) -> str:
    return "end" if state.get("error") or state.get("final_status") == "source_limited" else "next"


def _route_after_qa(state: GraphState) -> str:
    if state.get("error"):
        return "end"
    route = qa_routing(state)
    action = state.get("repair_action", "")
    if action == "drop_or_disclose":
        return "analyst"
    if route == "collector":
        return "discovery"
    return route


def _route_after_discovery(state: GraphState) -> str:
    if state.get("error") or state.get("final_status") == "source_limited":
        return "end"
    if state.get("repair_action") == "drop_or_disclose":
        return "analyst"
    return "collector"


def build_graph(checkpointer: Any = None, *, enable_qa: bool = True) -> StateGraph:
    """构建竞品分析StateGraph

    Args:
        checkpointer: LangGraph Checkpointer实例（如PostgresSaver），
                      传None则不持久化（适合测试）。

    Returns:
        编译后的StateGraph，可直接invoke/ainvoke。
    """
    graph = StateGraph(GraphState)

    # 添加节点
    graph.add_node("discovery", _observed_node("discovery", discovery_node))
    graph.add_node("collector", _observed_node("collector", collector_node))
    graph.add_node("analyst", _observed_node("analyst", analyst_node))
    graph.add_node("writer", _observed_node("writer", writer_node))
    if enable_qa:
        graph.add_node("qa", _observed_node("qa", qa_node))

    # Stop at the first node error, preserving its original cause. A source
    # limit is a normal end with the previous report and QA verdict intact.
    graph.add_conditional_edges(
        "discovery",
        _route_after_discovery,
        {"end": END, "collector": "collector", "analyst": "analyst"},
    )
    for name, next_name in (
        ("collector", "analyst"),
        ("analyst", "writer"),
        ("writer", "qa" if enable_qa else END),
    ):
        graph.add_conditional_edges(
            name,
            _continue_unless_failed,
            {"end": END, "next": next_name},
        )

    # QA后的条件边：根据verdict和target_agent路由
    if enable_qa:
        graph.add_conditional_edges(
            "qa",
            _route_after_qa,
            {
                "end": END,
                "discovery": "discovery",
                "analyst": "analyst",
                "writer": "writer",
            },
        )

    # 入口
    graph.set_entry_point("discovery")

    # 编译
    compile_kwargs: dict[str, Any] = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer

    return graph.compile(**compile_kwargs)


async def get_postgres_checkpointer(conn_string: str | None = None) -> Any:
    """创建PostgresSaver实例 - 用于断点续跑

    Args:
        conn_string: Postgres连接字符串，如"postgresql://user:pass@host:5432/db"
                     不传则从环境变量POSTGRES_URL读取

    Returns:
        PostgresSaver实例（已setup）

    Note:
        需要安装langgraph-checkpoint-postgres，未安装时会抛ImportError。
        生产环境建议使用此checkpointer，开发测试可用MemorySaver或不传。
    """
    import os

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    conn_string = conn_string or os.getenv(
        "POSTGRES_URL", "postgresql://localhost:5432/competitive_analysis"
    )

    saver = AsyncPostgresSaver.from_conn_string(conn_string)
    await saver.setup()
    return saver


async def run_pipeline(
    competitor_name: str,
    collect_scope: list[str] | None = None,
    target_urls: list[str] | None = None,
    expected_dimensions: list[str] | None = None,
    max_iterations: int = 3,
    checkpointer: Any = None,
    thread_id: str | None = None,
    discovery_strategy: str = "official_only",
    trusted_domains: list[str] | None = None,
    enable_qa: bool = True,
    execution_metadata: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """运行完整pipeline - 一站式入口

    Args:
        competitor_name: 竞品名称
        collect_scope: 初始采集维度，默认["pricing", "features", "user_personas"]
        target_urls: 指定URL，为空则自动发现
        expected_dimensions: 期望覆盖的完整维度列表（QA据此判定数据完整性）
        max_iterations: 最大反馈循环次数，默认3
        checkpointer: 持久化器，传None则不持久化
        thread_id: 会话ID，用于checkpoint恢复，不传则新建
        discovery_strategy: Discovery策略 - official_only / open_search
        trusted_domains: open_search策略下的权威媒体白名单

    Returns:
        最终GraphState（dict）
    """
    if max_iterations < 1:
        raise ValueError("max_iterations must be positive")
    app = build_graph(checkpointer=checkpointer, enable_qa=enable_qa)

    initial_state: GraphState = {
        "competitor_name": competitor_name,
        "collect_scope": collect_scope or ["pricing", "features", "user_personas"],
        "target_urls": target_urls or [],
        "expected_dimensions": expected_dimensions
        or (collect_scope or ["pricing", "features", "user_personas"]),
        "discovery_strategy": discovery_strategy,
        "trusted_domains": trusted_domains or [],
        "iteration": 1,
        "max_iterations": max_iterations,
        "feedback_history": [],
        "missing_dimensions": [],
        "repair_action": "",
        "attempted_urls": [],
        "trace_id": _make_trace_id(),
        "started_at": datetime.now().isoformat(),
        "final_status": "running",
    }

    config: dict[str, Any] = {}
    if checkpointer:
        config["configurable"] = {"thread_id": thread_id or str(uuid.uuid4())}
    config["recursion_limit"] = max_iterations * 6  # 每轮5个节点 + 余量

    records = execution_metadata if execution_metadata is not None else []
    token = execution_records.set(records)
    try:
        final_state = await app.ainvoke(initial_state, config=config)
    finally:
        execution_records.reset(token)
    final_state["execution_metadata"] = records
    final_state["enable_qa"] = enable_qa

    if "completed_at" not in final_state:
        final_state["completed_at"] = datetime.now().isoformat()
    if final_state.get("error"):
        final_state["final_status"] = "failed"
    elif final_state.get("final_status") == "running":
        final_state["final_status"] = "ended"

    return final_state
