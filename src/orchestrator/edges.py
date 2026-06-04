"""Conditional Edge路由逻辑

QA节点输出后，根据verdict和target_agent决定下一步：
- pass → END（流程完成）
- revise → collector/analyst/writer（根据问题类型路由到对应Agent）
- reject → END（严重质量问题，达到上限后终止）
- 达到max_iterations → END（强制结束，防止死循环）
"""

from __future__ import annotations

from typing import Any

from orchestrator.state import GraphState


def qa_routing(state: GraphState) -> str:
    """QA节点后的条件路由

    路由逻辑：
    - human_force_pass / human_abort → end
    - final_status == "running" → collector（人工打回重跑）
    - 达到最大迭代 → end
    - pass → end
    - revise/reject → 根据QA返回的target_agent路由到对应Agent
    - target_agent无效时降级到collector

    Returns:
        下一个node的名称，或"end"表示流程结束
    """
    verdict = state.get("qa_verdict", "reject")
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 3)
    final_status = state.get("final_status", "")

    # Human intervention overrides
    if final_status in ("human_force_pass", "human_abort", "completed", "qa_failed"):
        return "end"

    # Reject verdict sets final_status like "rejected(score=0.50)" — terminate
    if final_status.startswith("rejected"):
        return "end"

    if iteration > max_iterations:
        return "end"

    # Human requested a fresh run after QA passed. Do not let the initial
    # "running" status override reject/revise target routing.
    if verdict == "pass" and final_status == "running":
        return "collector"

    if verdict == "pass":
        return "end"

    # revise 或 reject 都可以打回重做（reject在未达上限时也允许重做）
    if verdict in ("revise", "reject"):
        target_agent = state.get("qa_target_agent", "collector")
        if target_agent not in ("collector", "analyst", "writer"):
            target_agent = "collector"
        return target_agent

    return "end"
