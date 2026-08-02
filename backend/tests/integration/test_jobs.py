"""Job queue and worker tests.

The queue is an abstraction whose only job is to be swappable. These tests
check the behaviour any implementation must have, so a future Celery-backed
queue can be validated against the same expectations.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from leadkhojo.core.utils.clock import utcnow
from leadkhojo.db.models import Business, Job, Scan
from leadkhojo.db.repository import ScanRepository
from leadkhojo.jobs.queue import JobQueue, JobStatus, JobType, PostgresJobQueue
from leadkhojo.jobs.worker import WorkerPool
from leadkhojo.plugins.engine import PluginEngine

pytestmark = pytest.mark.asyncio


@pytest.fixture
def queue(session) -> PostgresJobQueue:  # type: ignore[no-untyped-def]
    return PostgresJobQueue(session)


async def _scan(session) -> Scan:  # type: ignore[no-untyped-def]
    return await ScanRepository(session).create_scan(
        keyword="k", location=None, provider="csv_import", limit=25
    )


# ---------------------------------------------------------------- contract


async def test_the_postgres_queue_satisfies_the_protocol(queue: PostgresJobQueue) -> None:
    """The protocol is the seam. If an implementation drifts from it, the
    Celery swap stops being a drop-in."""
    assert isinstance(queue, JobQueue)


# ---------------------------------------------------------------- enqueue/claim


async def test_a_job_can_be_enqueued_and_claimed(queue: PostgresJobQueue, session) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    job_id = await queue.enqueue(JobType.DISCOVER, payload={"x": 1}, scan_id=scan.id)

    claimed = await queue.claim("worker-1")

    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.type == JobType.DISCOVER
    assert claimed.payload == {"x": 1}
    assert claimed.attempts == 1


async def test_an_empty_queue_returns_none(queue: PostgresJobQueue) -> None:
    assert await queue.claim("worker-1") is None


async def test_a_claimed_job_is_not_handed_out_twice(queue: PostgresJobQueue, session) -> None:  # type: ignore[no-untyped-def]
    """The core guarantee. On PostgreSQL this is FOR UPDATE SKIP LOCKED; the
    status predicate on the UPDATE makes it correct on SQLite too."""
    scan = await _scan(session)
    await queue.enqueue(JobType.DISCOVER, scan_id=scan.id)

    first = await queue.claim("worker-1")
    second = await queue.claim("worker-2")

    assert first is not None
    assert second is None


async def test_priority_orders_the_queue(queue: PostgresJobQueue, session) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    await queue.enqueue(JobType.FINALIZE_SCAN, scan_id=scan.id, priority=200)
    await queue.enqueue(JobType.ANALYZE_BUSINESS, scan_id=scan.id, priority=100)

    first = await queue.claim("worker-1")

    assert first is not None
    assert first.type == JobType.ANALYZE_BUSINESS


async def test_a_delayed_job_is_not_claimable_yet(queue: PostgresJobQueue, session) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    await queue.enqueue(JobType.FINALIZE_SCAN, scan_id=scan.id, delay_seconds=60)

    assert await queue.claim("worker-1") is None


# ---------------------------------------------------------------- lifecycle


async def test_completing_a_job_removes_it_from_the_queue(queue: PostgresJobQueue, session) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    job_id = await queue.enqueue(JobType.DISCOVER, scan_id=scan.id)
    await queue.claim("worker-1")

    await queue.complete(job_id)

    job = await session.get(Job, job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.completed_at is not None
    assert await queue.pending_count() == 0


async def test_a_failure_is_retried_with_backoff(queue: PostgresJobQueue, session) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    job_id = await queue.enqueue(JobType.DISCOVER, scan_id=scan.id)
    await queue.claim("worker-1")

    await queue.fail(job_id, "transient network error")

    job = await session.get(Job, job_id)
    assert job.status == JobStatus.PENDING  # back in the queue
    assert job.run_after > utcnow()  # but not immediately
    assert "transient" in job.error


async def test_a_job_that_exhausts_its_attempts_fails_visibly(
    queue: PostgresJobQueue, session
) -> None:  # type: ignore[no-untyped-def]
    """Silent job loss is the worst outcome: it looks like success."""
    scan = await _scan(session)
    job_id = await queue.enqueue(JobType.DISCOVER, scan_id=scan.id)

    for _ in range(3):
        await session.execute(
            update(Job).where(Job.id == job_id).values(status=JobStatus.PENDING, run_after=utcnow())
        )
        await queue.claim("worker-1")
        await queue.fail(job_id, "still broken")

    job = await session.get(Job, job_id)
    assert job.status == JobStatus.FAILED
    assert job.error


async def test_retry_can_be_disabled_for_unrecoverable_failures(
    queue: PostgresJobQueue, session
) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    job_id = await queue.enqueue(JobType.DISCOVER, scan_id=scan.id)
    await queue.claim("worker-1")

    await queue.fail(job_id, "unknown job type", retry=False)

    assert (await session.get(Job, job_id)).status == JobStatus.FAILED


async def test_stale_jobs_are_reclaimed(queue: PostgresJobQueue, session) -> None:  # type: ignore[no-untyped-def]
    """A worker killed mid-job would otherwise leave it RUNNING for ever and
    the scan would never finish."""
    from datetime import timedelta

    scan = await _scan(session)
    job_id = await queue.enqueue(JobType.DISCOVER, scan_id=scan.id)
    await queue.claim("dead-worker")
    await session.execute(
        update(Job).where(Job.id == job_id).values(locked_at=utcnow() - timedelta(hours=2))
    )

    reclaimed = await queue.reclaim_stale(older_than_seconds=900)

    assert reclaimed == 1
    assert (await session.get(Job, job_id)).status == JobStatus.PENDING


async def test_cancelling_a_scan_cancels_its_pending_jobs(queue: PostgresJobQueue, session) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    await queue.enqueue(JobType.ANALYZE_BUSINESS, scan_id=scan.id)
    await queue.enqueue(JobType.ANALYZE_BUSINESS, scan_id=scan.id)

    cancelled = await queue.cancel_scan_jobs(scan.id)

    assert cancelled == 2
    assert await queue.pending_count(scan.id) == 0


async def test_pending_count_is_scoped_to_a_scan(queue: PostgresJobQueue, session) -> None:  # type: ignore[no-untyped-def]
    first = await _scan(session)
    second = await _scan(session)
    await queue.enqueue(JobType.ANALYZE_BUSINESS, scan_id=first.id)
    await queue.enqueue(JobType.ANALYZE_BUSINESS, scan_id=second.id)

    assert await queue.pending_count(first.id) == 1
    assert await queue.pending_count() == 2


# ---------------------------------------------------------------- worker


@pytest.fixture
def pool(engine, test_settings):  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return WorkerPool(
        settings=test_settings,
        sessionmaker=factory,
        engine=PluginEngine([]),
    )


async def test_the_worker_executes_a_job_and_marks_it_complete(
    pool: WorkerPool, engine, session
) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    queue = PostgresJobQueue(session)
    await queue.enqueue(
        JobType.DISCOVER,
        payload={"csv_content": "domain\nacme.com\n"},
        scan_id=scan.id,
    )
    await session.commit()

    processed = await pool.drain(timeout=20)

    assert processed >= 1
    rows = (await session.scalars(select(Business).where(Business.scan_id == scan.id))).all()
    assert [b.domain for b in rows] == ["acme.com"]


async def test_discovery_fans_out_one_job_per_business(pool: WorkerPool, session) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    queue = PostgresJobQueue(session)
    await queue.enqueue(
        JobType.DISCOVER,
        payload={"csv_content": "domain\na.com\nb.com\nc.com\n"},
        scan_id=scan.id,
    )
    await session.commit()

    # Run only the discover job.
    await pool._run_one("test")

    analyze_jobs = (
        await session.scalars(
            select(Job).where(Job.scan_id == scan.id, Job.type == JobType.ANALYZE_BUSINESS)
        )
    ).all()
    assert len(analyze_jobs) == 3


async def test_an_unknown_job_type_fails_without_retrying(pool: WorkerPool, session) -> None:  # type: ignore[no-untyped-def]
    scan = await _scan(session)
    queue = PostgresJobQueue(session)
    job_id = await queue.enqueue("nonsense_job", scan_id=scan.id)
    await session.commit()

    await pool._run_one("test")
    await session.commit()

    job = await session.get(Job, job_id)
    await session.refresh(job)
    assert job.status == JobStatus.FAILED


async def test_a_handler_exception_does_not_kill_the_worker(
    pool: WorkerPool, session, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """One bad job must never stop the pool."""
    from leadkhojo.jobs import handlers

    async def _explode(ctx: object) -> None:
        raise RuntimeError("handler exploded")

    monkeypatch.setitem(handlers.HANDLERS, JobType.DISCOVER, _explode)

    scan = await _scan(session)
    job_id = await PostgresJobQueue(session).enqueue(JobType.DISCOVER, scan_id=scan.id)
    await session.commit()

    handled = await pool._run_one("test")

    assert handled is True  # the worker survived
    job = await session.get(Job, job_id)
    await session.refresh(job)
    assert "handler exploded" in (job.error or "")


async def test_draining_an_empty_queue_returns_zero(pool: WorkerPool) -> None:
    assert await pool.drain(timeout=5) == 0


async def test_finalize_waits_for_outstanding_analysis(pool: WorkerPool, session) -> None:  # type: ignore[no-untyped-def]
    """A finalize job that blocks a worker is a worker that cannot work.
    It should re-enqueue itself instead."""
    scan = await _scan(session)
    queue = PostgresJobQueue(session)
    await queue.enqueue(
        JobType.ANALYZE_BUSINESS,
        payload={"business_id": str(uuid.uuid4())},
        scan_id=scan.id,
        delay_seconds=300,
    )
    await queue.enqueue(JobType.FINALIZE_SCAN, scan_id=scan.id, priority=200)
    await session.commit()

    await pool._run_one("test")
    await session.commit()

    reloaded = await session.get(Scan, scan.id)
    await session.refresh(reloaded)
    assert reloaded.status != "completed", "finalize completed while work was outstanding"
