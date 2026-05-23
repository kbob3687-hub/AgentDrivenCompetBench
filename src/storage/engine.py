"""Async SQLAlchemy engine + session factory"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def _build_dsn() -> str:
    url = os.getenv("POSTGRES_URL")
    if url:
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
    user = os.getenv("POSTGRES_USER", "ca_user")
    password = os.getenv("POSTGRES_PASSWORD", "ca_password")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "competitive_analysis")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


async def init_engine() -> AsyncEngine:
    global _engine, _session_factory
    _engine = create_async_engine(_build_dsn(), pool_size=5, max_overflow=10)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker:
    if _session_factory is None:
        raise RuntimeError("Engine not initialized. Call init_engine() first.")
    return _session_factory


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Engine not initialized.")
    return _engine
