"""FastAPI dependencies.

The plugin engine and worker pool are process-wide singletons created during
startup. Building the engine loads and validates every rule pack, which must
happen once at boot — not per request, and not lazily inside a handler where
a malformed rule would surface as a 500 mid-scan.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from leadkhojo.api.service import ScanService
from leadkhojo.core.config import Settings, get_settings
from leadkhojo.db.session import get_session
from leadkhojo.jobs.queue import PostgresJobQueue
from leadkhojo.jobs.worker import WorkerPool
from leadkhojo.plugins.engine import PluginEngine

_engine: PluginEngine | None = None
_worker_pool: WorkerPool | None = None


def set_plugin_engine(engine: PluginEngine | None) -> None:
    global _engine
    _engine = engine


def get_plugin_engine() -> PluginEngine:
    if _engine is None:  # pragma: no cover - lifespan always sets this
        raise RuntimeError("Plugin engine not initialised. Did the lifespan run?")
    return _engine


def set_worker_pool(pool: WorkerPool | None) -> None:
    global _worker_pool
    _worker_pool = pool


def get_worker_pool() -> WorkerPool | None:
    return _worker_pool


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async for session in get_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_app_settings(request: Request) -> Settings:
    """The configuration this app was built with, not the global one.

    They are the same in production. They differ in tests, which is the
    point: nothing here reads configuration the caller cannot control.
    """
    settings: Settings | None = getattr(request.app.state, "settings", None)
    return settings or get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]


async def get_scan_service(session: SessionDep, settings: SettingsDep) -> ScanService:
    return ScanService(session, PostgresJobQueue(session), settings)


__all__ = [
    "SessionDep",
    "SettingsDep",
    "get_app_settings",
    "get_db_session",
    "get_plugin_engine",
    "get_scan_service",
    "get_worker_pool",
    "set_plugin_engine",
    "set_worker_pool",
]
