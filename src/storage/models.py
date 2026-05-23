"""SQLAlchemy ORM模型 - analysis_runs表"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    competitor_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    industry: Mapped[str] = mapped_column(String(100), nullable=False, default="saas")
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    qa_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    qa_verdict: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    report_length: Mapped[int] = mapped_column(Integer, default=0)
    sources_fetched: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_blob: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (Index("ix_analysis_runs_created_at", "created_at"),)
