"""Job handlers — the pipeline, driven by the queue.

A handler receives a JobHandle (a plain value) and a session. It knows
nothing about how it was scheduled, which is what allows the queue
implementation to change without touching any of this.

    discover          -> create businesses, enqueue one analyze per business
    analyze_business  -> crawl, run plugins, score, persist
    finalize_scan     -> mark the scan complete
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from leadkhojo.core.config import Settings
from leadkhojo.crawler.service import CrawlerService
from leadkhojo.db.repository import ScanRepository
from leadkhojo.discovery.providers import CsvImportProvider, DiscoveredBusiness
from leadkhojo.jobs.queue import JobHandle, JobQueue, JobType
from leadkhojo.pipeline.runner import PipelineRunner
from leadkhojo.plugins.engine import PluginEngine

logger = logging.getLogger(__name__)

JobHandler = Callable[["JobContext"], Awaitable[None]]


class JobContext:
    """Everything a handler needs, assembled by the worker."""

    __slots__ = ("engine", "job", "queue", "repo", "session", "settings")

    def __init__(
        self,
        *,
        job: JobHandle,
        session: AsyncSession,
        queue: JobQueue,
        settings: Settings,
        engine: PluginEngine,
    ) -> None:
        self.job = job
        self.session = session
        self.queue = queue
        self.settings = settings
        self.engine = engine
        self.repo = ScanRepository(session)


async def handle_discover(ctx: JobContext) -> None:
    """Turn a scan request into businesses, then fan out one job each."""
    scan_id = ctx.job.scan_id
    if scan_id is None:
        raise ValueError("discover job has no scan_id")

    scan = await ctx.repo.get_scan(scan_id)
    if scan is None:
        logger.warning("job.scan_missing", extra={"scan_id": str(scan_id)})
        return

    csv_content = ctx.job.payload.get("csv_content")
    if csv_content:
        result = CsvImportProvider(csv_content).parse(limit=scan.result_limit)
        discovered = result.businesses
    else:
        urls = ctx.job.payload.get("urls") or []
        discovered = tuple(_business_from_url(u) for u in urls)
        discovered = tuple(b for b in discovered if b is not None)  # type: ignore[misc]

    if not discovered:
        await ctx.repo.finish_scan(
            scan_id, status="failed", error="Discovery produced no businesses"
        )
        return

    rows = await ctx.repo.add_businesses(scan_id, discovered)
    await ctx.repo.mark_scan_running(scan_id, total=len(rows))

    for row in rows:
        if row.status == "no_website":
            continue
        await ctx.queue.enqueue(
            JobType.ANALYZE_BUSINESS,
            payload={"business_id": str(row.id)},
            scan_id=scan_id,
            priority=100,
        )

    # Lowest priority so it drains after every analysis job.
    await ctx.queue.enqueue(JobType.FINALIZE_SCAN, scan_id=scan_id, priority=200)


async def handle_analyze_business(ctx: JobContext) -> None:
    """Crawl and analyse one business."""
    business_id = uuid.UUID(ctx.job.payload["business_id"])

    business = await ctx.repo.get_business(business_id)
    if business is None:
        logger.warning("job.business_missing", extra={"business_id": str(business_id)})
        return

    discovered = DiscoveredBusiness(
        name=business.name,
        website_url=business.website_url,  # type: ignore[arg-type]
        domain=business.domain,  # type: ignore[arg-type]
        city=business.city,
        country_code=business.country_code,
        category=business.category,
        source=business.source_provider,
    )

    runner = PipelineRunner(ctx.settings, ctx.engine, CrawlerService(ctx.settings))
    result = await runner.analyze_one(discovered)

    await ctx.repo.save_result(business_id, result)
    if ctx.job.scan_id:
        await ctx.repo.update_progress(ctx.job.scan_id, current_business=business.name)


async def handle_finalize_scan(ctx: JobContext) -> None:
    """Close the scan once no analysis work remains.

    Re-enqueues itself if work is still outstanding rather than blocking a
    worker: a finalize job that waits is a worker that cannot do anything
    else.
    """
    scan_id = ctx.job.scan_id
    if scan_id is None:
        return

    outstanding = await ctx.queue.pending_count(scan_id)
    # This job is itself counted as running, hence > 1.
    if outstanding > 1:
        await ctx.queue.enqueue(
            JobType.FINALIZE_SCAN, scan_id=scan_id, priority=200, delay_seconds=2.0
        )
        return

    await ctx.repo.update_progress(scan_id)
    await ctx.repo.finish_scan(scan_id, status="completed")
    logger.info("scan.completed", extra={"scan_id": str(scan_id)})


HANDLERS: dict[str, JobHandler] = {
    JobType.DISCOVER: handle_discover,
    JobType.ANALYZE_BUSINESS: handle_analyze_business,
    JobType.FINALIZE_SCAN: handle_finalize_scan,
}


def _business_from_url(url: str) -> DiscoveredBusiness | None:
    from leadkhojo.core.utils.domains import canonical_domain, normalize_url

    normalized = normalize_url(url)
    domain = canonical_domain(url)
    if normalized is None or domain is None:
        return None
    return DiscoveredBusiness(name=domain, website_url=normalized, domain=domain, source="manual")


__all__ = ["HANDLERS", "JobContext", "JobHandler"]
