"""CRUD操作 - 分析结果的存取"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from storage.engine import get_session_factory
from storage.models import AnalysisRun

logger = logging.getLogger(__name__)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _row_to_summary(row: AnalysisRun) -> dict[str, Any]:
    return {
        "task_id": str(row.task_id),
        "competitor_name": row.competitor_name,
        "industry": row.industry,
        "status": row.status,
        "qa_score": row.qa_score,
        "qa_verdict": row.qa_verdict,
        "iteration": row.iteration,
        "report_length": row.report_length,
        "sources_fetched": row.sources_fetched,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


async def save_run(state: dict[str, Any], task_id: str, status: str) -> None:
    """持久化分析结果到PostgreSQL（失败不抛异常，仅记日志）"""
    try:
        factory = get_session_factory()
        run = AnalysisRun(
            task_id=uuid.UUID(task_id),
            competitor_name=state.get("competitor_name", "unknown"),
            industry=state.get("industry", "saas"),
            status=status,
            qa_score=state.get("qa_score"),
            qa_verdict=state.get("qa_verdict"),
            iteration=state.get("iteration", 1),
            report_length=state.get("report_length", 0),
            sources_fetched=state.get("sources_fetched", 0),
            started_at=_parse_iso(state.get("started_at")) or datetime.now(timezone.utc),
            completed_at=_parse_iso(state.get("completed_at")),
            report_markdown=state.get("report_markdown"),
            result_blob=state,
        )
        async with factory() as session:
            await session.merge(run)
            await session.commit()
        logger.info("Persisted run %s (status=%s)", task_id, status)
    except Exception:
        logger.exception("Failed to persist run %s", task_id)


async def get_run(task_id: str) -> dict[str, Any] | None:
    """从PG获取单个分析结果，返回完整result_blob"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(AnalysisRun, uuid.UUID(task_id))
            if not row:
                return None
            return {
                "status": row.status,
                "result": row.result_blob,
            }
    except Exception:
        logger.exception("Failed to get run %s", task_id)
        return None


async def list_runs(
    page: int = 1,
    page_size: int = 20,
    competitor_name: str | None = None,
    industry: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """分页查询历史分析记录"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            query = select(AnalysisRun).order_by(AnalysisRun.created_at.desc())
            count_query = select(func.count()).select_from(AnalysisRun)

            if competitor_name:
                query = query.where(AnalysisRun.competitor_name.ilike(f"%{competitor_name}%"))
                count_query = count_query.where(
                    AnalysisRun.competitor_name.ilike(f"%{competitor_name}%")
                )
            if industry:
                query = query.where(AnalysisRun.industry == industry)
                count_query = count_query.where(AnalysisRun.industry == industry)

            total = (await session.execute(count_query)).scalar() or 0
            query = query.offset((page - 1) * page_size).limit(page_size)
            rows = (await session.execute(query)).scalars().all()
            return [_row_to_summary(r) for r in rows], total
    except Exception:
        logger.exception("Failed to list runs")
        return [], 0
