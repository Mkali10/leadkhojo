"""Worker pool.

N asyncio tasks polling the job table, started in the FastAPI lifespan. Each
job runs in its own transaction, so one failure cannot roll back another's
work.

This is the piece that becomes a Celery worker later. Because handlers
receive a JobHandle rather than an ORM row, and enqueue through the JobQueue
protocol, that swap replaces this file and leaves the handlers untouched.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from leadkhojo.core.config import Settings
from leadkhojo.jobs.handlers import HANDLERS, JobContext
from leadkhojo.jobs.queue import PostgresJobQueue
from leadkhojo.plugins.engine import PluginEngine

logger = logging.getLogger(__name__)


class WorkerPool:
    """Runs jobs until stopped."""

    def __init__(
        self,
        *,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        engine: PluginEngine,
        queue_factory: Callable[[AsyncSession], PostgresJobQueue] = PostgresJobQueue,
    ) -> None:
        self._settings = settings
        self._sessionmaker = sessionmaker
        self._engine = engine
        self._queue_factory = queue_factory
        self._tasks: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()

    @property
    def running(self) -> bool:
        return bool(self._tasks) and not self._stopping.is_set()

    async def start(self) -> None:
        if self._tasks:
            return
        self._stopping.clear()
        count = max(1, self._settings.worker_count)
        self._tasks = [
            asyncio.create_task(self._loop(f"worker-{i}"), name=f"leadkhojo-worker-{i}")
            for i in range(count)
        ]
        self._tasks.append(asyncio.create_task(self._reclaim_loop(), name="leadkhojo-reclaimer"))
        logger.info("workers.started", extra={"count": count})

    async def stop(self, *, timeout: float = 10.0) -> None:  # noqa: ASYNC109
        """Ask workers to finish the job in hand, then cancel.

        A timeout parameter rather than asyncio.timeout at the call site:
        graceful shutdown needs to cancel *individual* tasks after the
        budget, not abandon the whole shutdown.
        """
        if not self._tasks:
            return
        self._stopping.set()

        done, pending = await asyncio.wait(self._tasks, timeout=timeout)
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._tasks.clear()
        logger.info("workers.stopped", extra={"drained": len(done)})

    async def drain(self, *, timeout: float = 60.0) -> int:  # noqa: ASYNC109
        """Run every queued job to completion. Used by tests and the CLI.

        Deterministic and single-threaded, which is what makes an end-to-end
        test of the job path possible without sleeping on a poll interval.
        """
        processed = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            handled = await self._run_one("drain")
            if not handled:
                break
            processed += 1
        return processed

    # -- internals ---------------------------------------------------------

    async def _loop(self, worker_id: str) -> None:
        while not self._stopping.is_set():
            try:
                handled = await self._run_one(worker_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker.loop_error", extra={"worker": worker_id})
                handled = False

            if not handled:
                with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._settings.worker_poll_seconds
                    )

    async def _run_one(self, worker_id: str) -> bool:
        """Claim and execute one job. Returns False when the queue is empty.

        The claim commits before the handler runs, so a crash mid-handler
        leaves the job RUNNING for the reclaimer rather than losing it.
        """
        async with self._sessionmaker() as session:
            queue = self._queue_factory(session)
            job = await queue.claim(worker_id)
            await session.commit()

        if job is None:
            return False

        handler = HANDLERS.get(job.type)
        if handler is None:
            logger.error("job.unknown_type", extra={"type": job.type})
            async with self._sessionmaker() as session:
                await self._queue_factory(session).fail(
                    job.id, f"Unknown job type: {job.type}", retry=False
                )
                await session.commit()
            return True

        try:
            async with self._sessionmaker() as session:
                ctx = JobContext(
                    job=job,
                    session=session,
                    queue=self._queue_factory(session),
                    settings=self._settings,
                    engine=self._engine,
                )
                await handler(ctx)
                await self._queue_factory(session).complete(job.id)
                await session.commit()
        except Exception as exc:
            logger.exception("job.handler_failed", extra={"job_id": str(job.id)})
            async with self._sessionmaker() as session:
                await self._queue_factory(session).fail(job.id, f"{type(exc).__name__}: {exc}")
                await self._mark_business_failed(session, job, exc)
                await session.commit()

        return True

    async def _mark_business_failed(
        self, session: AsyncSession, job: object, exc: Exception
    ) -> None:
        """A permanently failed analysis must leave the business marked.

        Otherwise it stays 'pending' for ever and the scan never finalises.
        """
        from leadkhojo.jobs.queue import JobHandle

        if not isinstance(job, JobHandle) or not job.is_final_attempt:
            return
        business_id = job.payload.get("business_id")
        if not business_id:
            return

        from leadkhojo.db.models import Business

        business = await session.get(Business, uuid.UUID(business_id))
        if business is not None and business.status not in ("completed", "failed"):
            business.status = "failed"
            business.failure_detail = f"{type(exc).__name__}: {exc}"[:1000]

    async def _reclaim_loop(self) -> None:
        """Return jobs abandoned by a dead worker to the queue."""
        interval = max(30.0, self._settings.worker_poll_seconds * 30)
        while not self._stopping.is_set():
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=interval)
            if self._stopping.is_set():
                return
            try:
                async with self._sessionmaker() as session:
                    await self._queue_factory(session).reclaim_stale(
                        self._settings.job_stale_after_seconds
                    )
                    await session.commit()
            except Exception:
                logger.exception("worker.reclaim_failed")


__all__ = ["WorkerPool"]
