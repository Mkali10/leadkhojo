"""Job queue abstraction.

The whole point of this module is the JobQueue protocol. Business logic
enqueues work and never learns how that work is delivered, so swapping
PostgresJobQueue for a Celery-backed implementation later touches this
package and nothing else.

PostgresJobQueue claims work with FOR UPDATE SKIP LOCKED, which is what lets
several workers — and later several processes — poll the same table without
ever double-claiming a job. SQLite has no row locking, so the claim falls
back to a guarded UPDATE that is correct for the single-process case the
test suite exercises.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from leadkhojo.core.utils.clock import utcnow
from leadkhojo.db.models import Job

logger = logging.getLogger(__name__)


class JobType(StrEnum):
    DISCOVER = "discover"
    ANALYZE_BUSINESS = "analyze_business"
    FINALIZE_SCAN = "finalize_scan"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class JobHandle:
    """A claimed unit of work, detached from the ORM.

    Deliberately a plain value: a handler receives this, not a Job row, so
    handlers cannot accidentally depend on a live session or on SQLAlchemy
    at all. That is what keeps the Celery swap cheap.
    """

    id: uuid.UUID
    type: str
    payload: dict[str, Any]
    scan_id: uuid.UUID | None
    attempts: int
    max_attempts: int

    @property
    def is_final_attempt(self) -> bool:
        return self.attempts >= self.max_attempts


@runtime_checkable
class JobQueue(Protocol):
    """What business logic is allowed to know about background work."""

    async def enqueue(
        self,
        job_type: str,
        *,
        payload: dict[str, Any] | None = None,
        scan_id: uuid.UUID | None = None,
        priority: int = 100,
        delay_seconds: float = 0.0,
    ) -> uuid.UUID: ...

    async def claim(self, worker_id: str) -> JobHandle | None: ...

    async def complete(self, job_id: uuid.UUID) -> None: ...

    async def fail(self, job_id: uuid.UUID, error: str, *, retry: bool = True) -> None: ...

    async def cancel_scan_jobs(self, scan_id: uuid.UUID) -> int: ...

    async def reclaim_stale(self, older_than_seconds: int) -> int: ...

    async def pending_count(self, scan_id: uuid.UUID | None = None) -> int: ...


class PostgresJobQueue:
    """Durable queue backed by the jobs table.

    No Redis, no broker. One fewer service to run, and `FOR UPDATE SKIP
    LOCKED` is sufficient well past the scale this product needs.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def _supports_skip_locked(self) -> bool:
        return self._session.bind.dialect.name == "postgresql"  # type: ignore[union-attr]

    async def enqueue(
        self,
        job_type: str,
        *,
        payload: dict[str, Any] | None = None,
        scan_id: uuid.UUID | None = None,
        priority: int = 100,
        delay_seconds: float = 0.0,
    ) -> uuid.UUID:
        job = Job(
            type=job_type,
            payload=payload or {},
            scan_id=scan_id,
            priority=priority,
            status=JobStatus.PENDING,
            run_after=utcnow() + timedelta(seconds=delay_seconds),
        )
        self._session.add(job)
        await self._session.flush()
        return job.id

    async def claim(self, worker_id: str) -> JobHandle | None:
        """Take the next runnable job, or return None.

        On PostgreSQL the SELECT ... FOR UPDATE SKIP LOCKED is the entire
        concurrency design: a row another worker is claiming is skipped
        rather than waited on.
        """
        now = utcnow()

        stmt = (
            select(Job.id)
            .where(Job.status == JobStatus.PENDING, Job.run_after <= now)
            .order_by(Job.priority, Job.created_at)
            .limit(1)
        )
        if self._supports_skip_locked:
            stmt = stmt.with_for_update(skip_locked=True)

        job_id = await self._session.scalar(stmt)
        if job_id is None:
            return None

        # The status predicate makes the claim atomic even without row locks:
        # a second worker updating the same row matches zero rows and moves on.
        result = await self._session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.PENDING)
            .values(
                status=JobStatus.RUNNING,
                locked_at=now,
                locked_by=worker_id,
                attempts=Job.attempts + 1,
            )
        )
        if not result.rowcount:
            return None  # lost the race; the caller polls again

        await self._session.flush()
        job = await self._session.get(Job, job_id)
        if job is None:  # pragma: no cover - defensive
            return None

        return JobHandle(
            id=job.id,
            type=job.type,
            payload=dict(job.payload or {}),
            scan_id=job.scan_id,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
        )

    async def complete(self, job_id: uuid.UUID) -> None:
        await self._session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(status=JobStatus.COMPLETED, completed_at=utcnow(), error=None)
        )

    async def fail(self, job_id: uuid.UUID, error: str, *, retry: bool = True) -> None:
        """Record a failure, retrying with backoff until attempts run out.

        A job that has exhausted its attempts stays visible as `failed` with
        the error attached. Silent job loss is the worst outcome here — it
        looks like success.
        """
        job = await self._session.get(Job, job_id)
        if job is None:
            return

        exhausted = not retry or job.attempts >= job.max_attempts
        if exhausted:
            job.status = JobStatus.FAILED
            job.completed_at = utcnow()
            logger.error(
                "job.failed_permanently",
                extra={"job_id": str(job_id), "type": job.type, "attempts": job.attempts},
            )
        else:
            # Exponential backoff: 2s, 4s, 8s ...
            backoff = 2 ** min(job.attempts, 6)
            job.status = JobStatus.PENDING
            job.run_after = utcnow() + timedelta(seconds=backoff)
            job.locked_at = None
            job.locked_by = None

        job.error = error[:2000]

    async def cancel_scan_jobs(self, scan_id: uuid.UUID) -> int:
        result = await self._session.execute(
            update(Job)
            .where(Job.scan_id == scan_id, Job.status == JobStatus.PENDING)
            .values(status=JobStatus.CANCELLED, completed_at=utcnow())
        )
        return int(result.rowcount or 0)

    async def reclaim_stale(self, older_than_seconds: int) -> int:
        """Return jobs abandoned by a dead worker to the queue.

        Without this, a worker killed mid-job leaves that job RUNNING for
        ever and the scan never completes.
        """
        cutoff = utcnow() - timedelta(seconds=older_than_seconds)
        result = await self._session.execute(
            update(Job)
            .where(Job.status == JobStatus.RUNNING, Job.locked_at < cutoff)
            .values(status=JobStatus.PENDING, locked_at=None, locked_by=None)
        )
        count = int(result.rowcount or 0)
        if count:
            logger.warning("job.reclaimed_stale", extra={"count": count})
        return count

    async def pending_count(self, scan_id: uuid.UUID | None = None) -> int:
        stmt = (
            select(text("count(*)"))
            .select_from(Job)
            .where(Job.status.in_((JobStatus.PENDING, JobStatus.RUNNING)))
        )
        if scan_id is not None:
            stmt = stmt.where(Job.scan_id == scan_id)
        return int(await self._session.scalar(stmt) or 0)


__all__ = [
    "JobHandle",
    "JobQueue",
    "JobStatus",
    "JobType",
    "PostgresJobQueue",
]
