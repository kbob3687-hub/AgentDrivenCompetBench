"""QAAgent - 质检Agent

对Analyst输出的CompetitorProfile和Writer输出的报告进行质量检查。
结合规则验证器（不依赖LLM）和Claude深度审查（语义一致性）。
"""

from __future__ import annotations

import json
import os
from typing import Any

from agents.base import AgentConfig, BaseAgent
from agents.qa.prompts import QA_SYSTEM_PROMPT, QA_USER_PROMPT_TEMPLATE
from agents.qa.validators import run_all_validators
from schemas.message import AgentMessage, MessageType, QAFeedback, QAIssue


class QAAgent(BaseAgent):
    """质检Agent

    工作流程：
    1. 规则验证器：四项硬性检查（不消耗token）
    2. LLM审查：Claude对语义一致性和事实准确性做深度检查
    3. 合并两轮结果，计算overall_score
    4. 根据分数判定verdict: pass/revise/reject
    """

    def default_config(self) -> AgentConfig:
        return AgentConfig(
            provider="openai_compat",
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            max_tokens=8192,
            temperature=0.0,
        )

    @property
    def role(self) -> str:
        return "qa"

    @property
    def system_prompt(self) -> str:
        return QA_SYSTEM_PROMPT

    async def run(self, message: AgentMessage) -> AgentMessage:
        """执行质检任务"""
        args = message.arguments
        competitor_name = args.get("competitor_name", "")
        profile = args.get("profile", {})
        report_markdown = args.get("report_markdown", "")
        original_claims = args.get("original_claims", [])
        expected_dimensions = args.get("expected_dimensions", [])
        industry = args.get("industry", "")

        if not profile:
            return self.build_message(
                to_agent="orchestrator",
                function_name="qa_result",
                arguments={"error": "no profile to check"},
                trace_id=message.trace_id,
                message_type=MessageType.TASK_RESULT,
                parent_message_id=message.message_id,
                context=message.context,
            )

        # ====== 第一轮：规则验证器（快速、免费） ======
        rule_issues, avg_confidence, checked, verified, missing_dimensions = run_all_validators(
            profile, original_claims or None, expected_dimensions or None, industry=industry
        )

        # ====== 第二轮：LLM深度审查 ======
        llm_issues = await self._llm_review(
            competitor_name, profile, report_markdown
        )

        # ====== 合并结果 ======
        all_issues = rule_issues + llm_issues

        # 计算overall_score
        overall_score = self._calculate_score(
            avg_confidence, all_issues, checked,
            llm_issue_count=len(llm_issues),
        )

        # 判定verdict - 维度缺失优先级最高
        if missing_dimensions:
            # 维度数据缺失 → 必须revise补采
            verdict = "revise"
        elif overall_score >= 0.70:
            verdict = "pass"
        elif overall_score >= 0.55:
            verdict = "revise"
        else:
            verdict = "reject"

        # 根据问题类型决定打回给谁
        target_agent = self._determine_target_agent(
            all_issues, missing_dimensions, verdict,
        )

        # 构造QAFeedback
        feedback = QAFeedback(
            target_agent=target_agent,
            issues=all_issues,
            overall_score=overall_score,
            verdict=verdict,
            summary=self._build_summary(verdict, all_issues, overall_score, missing_dimensions),
            checked_claims_count=checked,
            verified_claims_count=verified,
        )

        return self.build_message(
            to_agent="orchestrator",
            function_name="qa_result",
            arguments={
                "competitor_name": competitor_name,
                "feedback": feedback.model_dump(mode="json"),
                "verdict": verdict,
                "overall_score": overall_score,
                "issues_count": len(all_issues),
                "critical_issues": sum(1 for i in all_issues if i.severity == "critical"),
                "missing_dimensions": missing_dimensions,
            },
            trace_id=message.trace_id,
            message_type=MessageType.FEEDBACK if verdict != "pass" else MessageType.TASK_RESULT,
            parent_message_id=message.message_id,
            context=message.context,
        )

    async def _llm_review(
        self,
        competitor_name: str,
        profile: dict[str, Any],
        report_markdown: str,
    ) -> list[QAIssue]:
        """调用Claude进行语义层面的深度审查"""
        profile_json = json.dumps(profile, ensure_ascii=False, indent=2)
        if len(profile_json) > 10000:
            profile_json = profile_json[:10000] + "\n... (truncated)"

        if len(report_markdown) > 5000:
            report_markdown = report_markdown[:5000] + "\n... (truncated)"

        user_prompt = QA_USER_PROMPT_TEMPLATE.format(
            competitor_name=competitor_name,
            profile_json=profile_json,
            report_markdown=report_markdown or "(报告尚未生成)",
        )

        response = await self.call_llm(
            messages=[{"role": "user", "content": user_prompt}]
        )

        return self._parse_llm_issues(response.text)

    def _parse_llm_issues(self, text: str) -> list[QAIssue]:
        """解析LLM输出的issues"""
        parsed = self._parse_json(text)
        if not parsed:
            return []

        issues = []
        for item in parsed.get("issues", []):
            try:
                issues.append(QAIssue(
                    field_path=item.get("field_path", "*"),
                    issue_type=item.get("issue_type", "factual_error"),
                    severity=item.get("severity", "minor"),
                    description=item.get("description", ""),
                    suggestion=item.get("suggestion"),
                    evidence=item.get("evidence"),
                ))
            except Exception:
                continue

        return issues

    def _parse_json(self, text: str) -> dict[str, Any] | None:
        """解析JSON，容错"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1:
            try:
                return json.loads(text[first:last + 1])
            except json.JSONDecodeError:
                pass

        return None

    def _calculate_score(
        self,
        avg_confidence: float,
        issues: list[QAIssue],
        total_claims: int,
        llm_issue_count: int = 0,
    ) -> float:
        """计算综合质量分数

        设计原则：
        - 规则验证器（客观）：全额扣分，上限0.20
        - LLM审查（主观）：降权扣分，上限0.10
        - 两者合计上限0.25（保证高confidence数据不会被主观意见否决）
        """
        if total_claims == 0:
            return 0.0

        score = avg_confidence

        penalty_map = {"critical": 0.10, "major": 0.04, "minor": 0.01}

        rule_issues = issues[: len(issues) - llm_issue_count]
        llm_issues = issues[len(issues) - llm_issue_count:]

        rule_penalty = min(
            sum(penalty_map.get(i.severity, 0.01) for i in rule_issues),
            0.20,
        )
        llm_penalty = min(
            sum(penalty_map.get(i.severity, 0.01) for i in llm_issues) * 0.4,
            0.10,
        )

        total_penalty = min(rule_penalty + llm_penalty, 0.25)
        score -= total_penalty

        return max(0.0, min(1.0, round(score, 2)))

    def _determine_target_agent(
        self,
        issues: list[QAIssue],
        missing_dimensions: list[str],
        verdict: str,
    ) -> str:
        """根据问题类型决定打回给哪个Agent

        路由规则：
        - 缺失维度 → collector（数据没采到）
        - 数据相关问题（missing_source/factual_error/outdated）→ collector
        - 分析相关问题（low_confidence/inconsistency）→ analyst
        - 报告相关问题（schema_violation/结构问题）→ writer
        - 混合问题 → 按严重程度最高的issue决定
        """
        if verdict == "pass":
            return "collector"

        if missing_dimensions:
            return "collector"

        # 按问题类型分类
        data_issue_types = {"missing_source", "factual_error", "outdated"}
        analysis_issue_types = {"low_confidence", "inconsistency"}
        report_issue_types = {"schema_violation"}

        data_issues = [i for i in issues if i.issue_type in data_issue_types]
        analysis_issues = [i for i in issues if i.issue_type in analysis_issue_types]
        report_issues = [i for i in issues if i.issue_type in report_issue_types]

        # 按严重程度加权计分
        severity_weight = {"critical": 3, "major": 2, "minor": 1}
        data_score = sum(severity_weight.get(i.severity, 1) for i in data_issues)
        analysis_score = sum(severity_weight.get(i.severity, 1) for i in analysis_issues)
        report_score = sum(severity_weight.get(i.severity, 1) for i in report_issues)

        # 路由到得分最高的类别对应Agent
        if data_score == 0 and analysis_score == 0 and report_score == 0:
            # 无法分类的问题，按verdict默认路由
            return "analyst" if verdict == "reject" else "collector"

        scores = {
            "collector": data_score,
            "analyst": analysis_score,
            "writer": report_score,
        }
        return max(scores, key=scores.get)

    def _build_summary(
        self, verdict: str, issues: list[QAIssue], score: float,
        missing_dimensions: list[str] | None = None,
    ) -> str:
        """生成质检总结"""
        critical = sum(1 for i in issues if i.severity == "critical")
        major = sum(1 for i in issues if i.severity == "major")
        minor = sum(1 for i in issues if i.severity == "minor")

        if missing_dimensions:
            dims_str = "、".join(missing_dimensions)
            return f"数据不完整(score={score:.2f})。缺失维度: {dims_str}，需要补充采集后重新分析。"
        elif verdict == "pass":
            return f"质检通过(score={score:.2f})。发现{len(issues)}个问题(critical={critical}, major={major}, minor={minor})，均在可接受范围内。"
        elif verdict == "revise":
            return f"需要修改(score={score:.2f})。发现{critical}个严重问题、{major}个主要问题需修复后重新提交。"
        else:
            return f"质量不达标(score={score:.2f})。存在{critical}个严重问题，建议重新采集数据并分析。"
