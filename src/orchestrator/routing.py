"""Failure attribution helpers for graph routing decisions."""

from __future__ import annotations

from typing import Any

from orchestrator.state import GraphState


def _shorten(value: str, limit: int = 260) -> str:
    value = " ".join(str(value).split())
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _summarize_collect_errors(errors: list[str]) -> tuple[list[str], list[str]]:
    samples = [_shorten(e) for e in errors[:3]]
    joined = "\n".join(errors).lower()
    reasons: list[str] = []

    def add(label: str) -> None:
        if label not in reasons:
            reasons.append(label)

    if "paymentrequirederror" in joined or "insufficient credits" in joined:
        add("Firecrawl 额度不足")
    if "内容过短" in joined:
        add("HTTP 只抓到 JS 空壳/短内容")
    if "notimplementederror" in joined:
        add("Playwright 本地渲染不可用")
    if "connecterror" in joined:
        add("网络连接失败")
    if "robots.txt disallowed" in joined:
        add("robots.txt 禁止抓取")
    if "http 404" in joined or "404: not found" in joined:
        add("URL 返回 404")

    if not reasons and errors:
        add("采集器抓取或抽取失败")

    return reasons, samples


def classify_no_profile_failure(state: GraphState) -> dict[str, Any]:
    """Attribute an empty profile to the upstream node that can fix it.

    No profile is only an analyst problem when the analyst had claims to work
    with. If no claims exist, rerunning the analyst just repeats the symptom;
    the collector must produce evidence first.
    """
    claims = state.get("claims") or []
    collect_errors = state.get("collect_errors") or []
    discovered_urls = state.get("discovered_urls") or []
    collect_scope = state.get("collect_scope") or []
    discovery_strategy = state.get("discovery_strategy", "official_only")

    if not claims:
        if not discovered_urls:
            reason = "collector_no_sources"
            summary = "Discovery 没找到可采集 URL，所以 Collector 没有证据可抽取。"
            message = (
                "采集 0 条数据，无法生成报告。系统没有发现可用 URL。"
                "请换 discovery_strategy，或人工补充 2-3 个可直接访问的数据源。"
            )
            error_samples: list[str] = []
            failure_reasons = ["未发现 URL"]
        elif collect_errors:
            reason = "collector_fetch_failed"
            failure_reasons, error_samples = _summarize_collect_errors(collect_errors)
            reason_text = " / ".join(failure_reasons)
            summary = (
                f"已发现 {len(discovered_urls)} 个 URL，但 Collector 抓取/抽取失败，"
                f"没有产出 claims。主要原因：{reason_text}。"
            )
            message = (
                f"已发现 {len(discovered_urls)} 个 URL，但本轮采集 0 条数据，无法生成报告。"
                f"主要失败原因：{reason_text}。"
                "请补充可直接访问的页面，或修复本地 Playwright/开启受控付费抓取后重试。"
            )
        else:
            reason = "collector_no_claims"
            summary = f"已发现 {len(discovered_urls)} 个 URL，但 Collector 没抽出任何 claims。"
            message = (
                f"已发现 {len(discovered_urls)} 个 URL，但页面内容没有被抽取成结构化证据。"
                "请检查页面内容是否过短、是否与分析维度无关，或补充更明确的数据源。"
            )
            error_samples = []
            failure_reasons = ["未抽出 claims"]

        suggested_strategy = ""
        if (
            reason in {"collector_no_sources", "collector_fetch_failed"}
            and discovery_strategy == "official_only"
        ):
            suggested_strategy = "open_search"

        return {
            "target_agent": "collector",
            "reason": reason,
            "summary": summary,
            "message": message,
            "error_samples": error_samples,
            "failure_reasons": failure_reasons,
            "suggested_strategy": suggested_strategy,
            "missing_dimensions": list(collect_scope),
        }

    return {
        "target_agent": "analyst",
        "reason": "analyst_empty_profile",
        "summary": f"Collector 已产出 {len(claims)} 条 claims，但 Analyst 没生成 profile。",
        "message": (
            f"Collector 已产出 {len(claims)} 条证据，但 Analyst 没生成结构化 profile。"
            "下一轮应打回 Analyst 重新分析，而不是重新抓取。"
        ),
        "error_samples": [],
        "failure_reasons": ["Analyst 输出为空"],
        "suggested_strategy": "",
        "missing_dimensions": [],
    }
