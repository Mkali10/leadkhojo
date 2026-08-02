"""Application service — the layer between HTTP and the database.

Routers parse and serialize; this decides. Keeping the mapping here means
the React UI and the CLI can produce identical answers, and a future
GraphQL or gRPC surface would reuse it unchanged.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from leadkhojo.api import schemas
from leadkhojo.core.config import Settings
from leadkhojo.core.errors import ConflictError, NotFoundError, ValidationError
from leadkhojo.core.utils.clock import utcnow
from leadkhojo.db.models import Business, Scan
from leadkhojo.db.repository import ScanRepository
from leadkhojo.jobs.queue import JobQueue, JobType


class ScanService:
    def __init__(self, session: AsyncSession, queue: JobQueue, settings: Settings) -> None:
        self._session = session
        self._repo = ScanRepository(session)
        self._queue = queue
        self._settings = settings

    # -- creating ----------------------------------------------------------

    async def create_scan(self, request: schemas.CreateScanRequest) -> Scan:
        if not request.is_valid_request():
            raise ValidationError(
                "Provide either a list of urls or a keyword to search for.",
                meta={"fields": ["urls", "keyword"]},
            )

        scan = await self._repo.create_scan(
            keyword=request.keyword,
            location=request.location,
            provider=request.provider,
            limit=request.limit,
        )
        await self._queue.enqueue(
            JobType.DISCOVER,
            payload={"urls": request.urls},
            scan_id=scan.id,
            priority=10,
        )
        return scan

    async def create_scan_from_csv(self, request: schemas.CreateScanFromCsvRequest) -> Scan:
        scan = await self._repo.create_scan(
            keyword=None, location=None, provider="csv_import", limit=request.limit
        )
        await self._queue.enqueue(
            JobType.DISCOVER,
            payload={"csv_content": request.csv_content},
            scan_id=scan.id,
            priority=10,
        )
        return scan

    async def rerun_scan(self, scan_id: uuid.UUID) -> Scan:
        """Re-scan the same targets as a NEW scan.

        A new scan rather than overwriting: keeping both is what makes
        comparison possible, and comparison is the whole point of re-running.
        """
        original = await self._require_scan(scan_id)
        if not original.is_terminal:
            raise ConflictError(
                "That scan is still running. Wait for it to finish, or cancel it first.",
                meta={"scan_id": str(scan_id), "status": original.status},
            )

        businesses = await self._repo.list_businesses(
            scan_id, status="all", limit=self._settings.max_businesses_per_scan
        )
        urls = [b.website_url for b in businesses if b.website_url]
        if not urls:
            raise ConflictError(
                "That scan has no websites to re-run.", meta={"scan_id": str(scan_id)}
            )

        scan = await self._repo.create_scan(
            keyword=original.keyword,
            location=original.location,
            provider=original.provider,
            limit=original.result_limit,
            rerun_of_id=original.id,
        )
        await self._queue.enqueue(
            JobType.DISCOVER, payload={"urls": urls}, scan_id=scan.id, priority=10
        )
        return scan

    async def cancel_scan(self, scan_id: uuid.UUID) -> Scan:
        scan = await self._require_scan(scan_id)
        if scan.is_terminal:
            raise ConflictError(
                f"That scan is already {scan.status}.", meta={"status": scan.status}
            )
        await self._queue.cancel_scan_jobs(scan_id)
        await self._repo.finish_scan(scan_id, status="cancelled")
        return await self._require_scan(scan_id)

    async def delete_scan(self, scan_id: uuid.UUID) -> None:
        await self._require_scan(scan_id)
        await self._queue.cancel_scan_jobs(scan_id)
        await self._repo.delete_scan(scan_id)

    # -- reading -----------------------------------------------------------

    async def get_scan(self, scan_id: uuid.UUID) -> schemas.ScanSummary:
        return schemas.ScanSummary.model_validate(await self._require_scan(scan_id))

    async def list_scans(self, *, limit: int, offset: int) -> schemas.ScanListResponse:
        scans = await self._repo.list_scans(limit=limit, offset=offset)
        return schemas.ScanListResponse(
            data=[schemas.ScanSummary.model_validate(s) for s in scans],
            pagination=schemas.Pagination(
                total=await self._repo.count_scans(), limit=limit, offset=offset
            ),
        )

    async def get_progress(self, scan_id: uuid.UUID) -> schemas.ScanProgress:
        scan = await self._require_scan(scan_id)
        elapsed = None
        if scan.started_at:
            end = scan.completed_at or utcnow()
            elapsed = max(0, int((end - scan.started_at).total_seconds()))

        return schemas.ScanProgress(
            id=scan.id,
            status=scan.status,
            total_businesses=scan.total_businesses,
            completed_count=scan.completed_count,
            failed_count=scan.failed_count,
            percent_complete=scan.percent_complete,
            current_business=scan.current_business,
            elapsed_seconds=elapsed,
            error_message=scan.error_message,
        )

    async def list_businesses(
        self,
        scan_id: uuid.UUID,
        *,
        sort: str,
        order: str,
        status: str,
        has_contact: bool | None,
        min_opportunity_score: int | None,
        limit: int,
        offset: int,
    ) -> schemas.BusinessListResponse:
        scan = await self._require_scan(scan_id)
        rows = await self._repo.list_businesses(
            scan_id,
            sort=sort,
            order=order,
            status=status,
            has_contact=has_contact,
            min_opportunity_score=min_opportunity_score,
            limit=limit,
            offset=offset,
        )
        return schemas.BusinessListResponse(
            data=[_to_row(b) for b in rows],
            pagination=schemas.Pagination(
                total=await self._repo.count_businesses(scan_id, status=status),
                limit=limit,
                offset=offset,
            ),
            scan_status=scan.status,
        )

    async def get_business(self, business_id: uuid.UUID) -> schemas.BusinessDetail:
        business = await self._repo.get_business(business_id)
        if business is None:
            raise NotFoundError(f"No business with id {business_id}.")

        snapshot = None
        if business.snapshot is not None:
            snapshot = schemas.SnapshotMeta(
                captured_at=business.snapshot.captured_at,
                render_mode=business.snapshot.render_mode,
                status=business.snapshot.status,
                page_count=business.snapshot.page_count,
                duration_ms=business.snapshot.duration_ms,
                final_url=business.snapshot.final_url,
            )

        return schemas.BusinessDetail(
            id=business.id,
            scan_id=business.scan_id,
            name=business.name,
            domain=business.domain,
            website_url=business.website_url,
            final_url=business.final_url,
            city=business.city,
            country_code=business.country_code,
            status=business.status,
            failure_reason=business.failure_reason,
            failure_detail=business.failure_detail,
            contacts=[
                schemas.ContactDetail(
                    kind=str(c.get("kind", "")),
                    category=str(c.get("category", "")),
                    value=str(c.get("value", "")),
                    source_url=str(c.get("source_url", "")),
                )
                for c in (business.contacts or [])
            ],
            primary_email=business.primary_email,
            primary_phone=business.primary_phone,
            technologies=[_to_technology(t) for t in (business.technologies or [])],
            findings=[schemas.FindingDetail.model_validate(f) for f in business.findings],
            opportunities=[
                schemas.OpportunityDetail.model_validate(o) for o in business.opportunities
            ],
            scores=business.scores.breakdowns if business.scores else None,
            snapshot=snapshot,
            analyzed_at=business.analyzed_at,
        )

    # -- comparison --------------------------------------------------------

    async def compare_scans(
        self, base_id: uuid.UUID, compare_id: uuid.UUID
    ) -> schemas.ScanComparison:
        """Diff two scans by domain.

        This is what turns a one-off audit into something worth repeating:
        'their DMARC disappeared since last month' is a reason to call.
        """
        await self._require_scan(base_id)
        await self._require_scan(compare_id)

        before = await self._repo.business_summaries(base_id)
        after = await self._repo.business_summaries(compare_id)

        comparisons: list[schemas.BusinessComparison] = []
        counts = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}

        for domain in sorted(set(before) | set(after)):
            old, new = before.get(domain), after.get(domain)

            if old is None and new is not None:
                counts["added"] += 1
                comparisons.append(
                    schemas.BusinessComparison(domain=domain, name=str(new["name"]), state="added")
                )
                continue

            if new is None and old is not None:
                counts["removed"] += 1
                comparisons.append(
                    schemas.BusinessComparison(
                        domain=domain, name=str(old["name"]), state="removed"
                    )
                )
                continue

            assert old is not None and new is not None
            comparison = _diff(domain, old, new)
            counts[comparison.state] += 1  # type: ignore[index]
            comparisons.append(comparison)

        return schemas.ScanComparison(
            base_scan_id=base_id,
            compare_scan_id=compare_id,
            total_compared=len(comparisons),
            added=counts["added"],
            removed=counts["removed"],
            changed=counts["changed"],
            unchanged=counts["unchanged"],
            businesses=comparisons,
        )

    # -- internals ---------------------------------------------------------

    async def _require_scan(self, scan_id: uuid.UUID) -> Scan:
        scan = await self._repo.get_scan(scan_id)
        if scan is None:
            raise NotFoundError(f"No scan with id {scan_id}.")
        return scan


def _diff(domain: str, old: dict[str, Any], new: dict[str, Any]) -> schemas.BusinessComparison:
    old_scores = old["scores"]
    new_scores = new["scores"]

    score_deltas: dict[str, schemas.ScoreDelta] = {}
    for key in ("lead", "website", "security", "opportunity"):
        before, after = old_scores.get(key), new_scores.get(key)
        change = (after - before) if (before is not None and after is not None) else None
        score_deltas[key] = schemas.ScoreDelta(before=before, after=after, change=change)

    old_rules = set(old["opportunity_rule_ids"])
    new_rules = set(new["opportunity_rule_ids"])
    old_tech = set(old["technologies"])
    new_tech = set(new["technologies"])

    gained = sorted(new_rules - old_rules)
    resolved = sorted(old_rules - new_rules)
    tech_added = sorted(new_tech - old_tech)
    tech_removed = sorted(old_tech - new_tech)

    changed = bool(
        gained
        or resolved
        or tech_added
        or tech_removed
        or any(d.change for d in score_deltas.values())
    )

    return schemas.BusinessComparison(
        domain=domain,
        name=str(new["name"]),
        state="changed" if changed else "unchanged",
        scores=score_deltas,
        opportunities_gained=gained,
        opportunities_resolved=resolved,
        technologies_added=tech_added,
        technologies_removed=tech_removed,
    )


def _to_technology(raw: dict[str, Any]) -> schemas.TechnologySummary:
    return schemas.TechnologySummary(
        name=str(raw.get("name", "")),
        category=raw.get("category"),
        version=raw.get("version"),
        is_outdated=raw.get("is_outdated"),
    )


def _to_row(business: Business) -> schemas.BusinessRow:
    opportunities = sorted(
        business.opportunities,
        key=lambda o: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(o.urgency, 9),
            o.rule_id,
        ),
    )
    top = opportunities[0] if opportunities else None

    technologies: Sequence[dict[str, Any]] = business.technologies or []

    return schemas.BusinessRow(
        id=business.id,
        name=business.name,
        domain=business.domain,
        website_url=business.website_url,
        city=business.city,
        country_code=business.country_code,
        status=business.status,
        failure_reason=business.failure_reason,
        # null, never a guess — the no-synthesis rule reaches the wire.
        primary_email=business.primary_email,
        primary_phone=business.primary_phone,
        contact_count=len(business.contacts or []),
        scores=schemas.ScoreSet(
            lead=business.scores.lead_score if business.scores else None,
            website=business.scores.website_score if business.scores else None,
            security=business.scores.security_score if business.scores else None,
            opportunity=business.scores.opportunity_score if business.scores else None,
        ),
        top_technologies=[_to_technology(t) for t in technologies[:5]],
        opportunity_count=len(business.opportunities),
        top_opportunity=(
            schemas.OpportunitySummary(
                rule_id=top.rule_id,
                title=top.title,
                category=top.category,
                urgency=top.urgency,
            )
            if top
            else None
        ),
        critical_findings=_count_findings(business, "critical"),
        high_findings=_count_findings(business, "high"),
        scanned_at=business.analyzed_at,
    )


def _count_findings(business: Business, severity: str) -> int:
    """Counts come from the stored artifacts, not a lazy relationship load.

    The list endpoint deliberately does not eager-load findings — a 100-row
    page would otherwise fan out into 100 extra queries.
    """
    summary = (business.artifacts or {}).get("_finding_counts", {})
    if isinstance(summary, dict) and severity in summary:
        return int(summary[severity])
    return 0


__all__ = ["ScanService"]
