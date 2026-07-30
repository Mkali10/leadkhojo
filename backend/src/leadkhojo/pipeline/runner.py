"""Pipeline orchestration.

    discover -> crawl -> plugin engine -> score -> result

Concurrency: up to N sites at once, but the crawler enforces one request per
host, so breadth never becomes depth on any single server.

One site failing never fails the run. Every business gets a result object,
even if that result records why it could not be analyzed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from leadkhojo.core.config import Settings
from leadkhojo.core.findings import Finding
from leadkhojo.core.types import CrawlFailure, SnapshotStatus
from leadkhojo.core.utils.clock import utcnow
from leadkhojo.crawler.service import CrawlerService
from leadkhojo.crawler.snapshot import SiteSnapshot
from leadkhojo.discovery.providers import DiscoveredBusiness
from leadkhojo.opportunities.schemas import Opportunity
from leadkhojo.plugins.engine import EngineReport, PluginEngine
from leadkhojo.scoring.engine import Scores, compute_scores

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BusinessResult:
    business: DiscoveredBusiness
    snapshot: SiteSnapshot | None = None
    findings: tuple[Finding, ...] = ()
    opportunities: tuple[Opportunity, ...] = ()
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    scores: Scores | None = None
    error: str | None = None
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.snapshot is not None and self.snapshot.status is not SnapshotStatus.FAILED

    @property
    def failure_reason(self) -> CrawlFailure | None:
        return self.snapshot.failure_reason if self.snapshot else None

    def artifact(self, plugin_id: str, key: str, default: Any = None) -> Any:
        return self.artifacts.get(plugin_id, {}).get(key, default)


@dataclass(frozen=True, slots=True)
class ScanResult:
    results: tuple[BusinessResult, ...]
    started_at: datetime
    completed_at: datetime
    discovery_errors: tuple[str, ...] = ()

    @property
    def duration_seconds(self) -> float:
        return (self.completed_at - self.started_at).total_seconds()

    @property
    def succeeded(self) -> tuple[BusinessResult, ...]:
        return tuple(r for r in self.results if r.ok)

    @property
    def failed(self) -> tuple[BusinessResult, ...]:
        return tuple(r for r in self.results if not r.ok)

    def ranked_by(self, score: str = "opportunity") -> tuple[BusinessResult, ...]:
        def key(result: BusinessResult) -> int:
            if result.scores is None:
                return -1
            return int(getattr(result.scores, score).total)

        return tuple(sorted(self.succeeded, key=key, reverse=True))


class PipelineRunner:
    def __init__(
        self,
        settings: Settings,
        engine: PluginEngine,
        crawler: CrawlerService | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self._crawler = crawler or CrawlerService(settings)

    async def run(
        self,
        businesses: tuple[DiscoveredBusiness, ...],
        *,
        on_progress: Any = None,
    ) -> ScanResult:
        started_at = utcnow()
        semaphore = asyncio.Semaphore(self._settings.max_concurrent_sites)
        completed = 0
        total = len(businesses)

        async def process(business: DiscoveredBusiness) -> BusinessResult:
            nonlocal completed
            async with semaphore:
                result = await self.analyze_one(business)
            completed += 1
            if on_progress is not None:
                on_progress(completed, total, business.name)
            return result

        results = await asyncio.gather(*(process(b) for b in businesses), return_exceptions=False)

        return ScanResult(
            results=tuple(results),
            started_at=started_at,
            completed_at=utcnow(),
        )

    async def analyze_one(self, business: DiscoveredBusiness) -> BusinessResult:
        """Crawl and analyze one business. Never raises."""
        import time

        started = time.perf_counter()

        if not business.has_website:
            return BusinessResult(
                business=business,
                error="No website to analyze",
                duration_ms=0,
            )

        try:
            snapshot = await self._crawler.crawl(str(business.website_url))
        except Exception as exc:
            logger.exception("pipeline.crawl_failed", extra={"domain": business.domain})
            return BusinessResult(
                business=business,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

        report: EngineReport = self._engine.run(snapshot, now=snapshot.captured_at)

        artifacts = {pid: dict(values) for pid, values in report.artifacts.items()}
        scores = compute_scores(report.findings, report.opportunities, artifacts)

        if report.failed_plugins:
            logger.warning(
                "pipeline.plugins_failed",
                extra={"domain": business.domain, "plugins": report.failed_plugins},
            )

        return BusinessResult(
            business=business,
            snapshot=snapshot,
            findings=report.findings,
            opportunities=report.opportunities,
            artifacts=artifacts,
            scores=scores,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


__all__ = ["BusinessResult", "PipelineRunner", "ScanResult"]
