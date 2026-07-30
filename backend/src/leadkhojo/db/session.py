"""Async engine and session management.

One engine per process, created lazily so importing this module does not
open a connection — which matters for the CLI, which runs the whole
pipeline without a database.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from leadkhojo.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs(settings: Settings) -> dict[str, object]:
    url = settings.database_url
    if url.startswith("sqlite"):
        # SQLite has no pool to configure and rejects pool_size.
        return {"echo": settings.debug}
    return {
        "echo": settings.debug,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,  # a recycled dead connection is a 500 nobody understands
        "pool_recycle": 1800,
    }


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        resolved = settings or get_settings()
        _engine = create_async_engine(resolved.database_url, **_engine_kwargs(resolved))  # type: ignore[arg-type]
        logger.info("db.engine_created", extra={"dialect": _engine.dialect.name})
    return _engine


def get_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(settings),
            expire_on_commit=False,  # results stay usable after commit
            autoflush=False,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope(
    settings: Settings | None = None,
) -> AsyncIterator[AsyncSession]:
    """A transactional scope. Commits on success, rolls back on failure."""
    factory = get_sessionmaker(settings)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session


async def dispose_engine() -> None:
    """Close the pool. Called on application shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        logger.info("db.engine_disposed")
    _engine = None
    _sessionmaker = None


def reset_engine_for_testing() -> None:
    """Drop cached engine state so a test can point at its own database."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


__all__ = [
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "reset_engine_for_testing",
    "session_scope",
]
