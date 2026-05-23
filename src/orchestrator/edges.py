"""Conditional Edge路由逻辑

QA节点输出后，根据verdict决定下一步：
- pass → END（流程完成）
- revise → collector（数据不完整，补采缺失维度）
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
    - revise → collector（补采缺失维度后重走全流程）
    - reject → end（质量太差，不再重试）

    Returns:
        下一个node的名称，或"end"表示流程结束
    """
    verdict = state.get("qa_verdict", "reject")
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 3)
    final_status = state.get("final_status", "")

    # Human intervention overrides
    if final_status in ("human_force_pass", "human_abort", "completed"):
        return "end"

    # Human requested re-run after pass
    if final_status == "running":
        return "collector"

    if iteration > max_iterations:
        return "end"

    if verdict == "pass":
        return "end"
    elif verdict == "revise":
        return "collector"
    elif verdict == "reject":
        return "end"
    else:
        return "end"
