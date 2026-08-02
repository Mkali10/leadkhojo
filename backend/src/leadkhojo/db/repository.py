"""Persistence for scans and their results.

All database access goes through here. Nothing else in the codebase issues
a query — which is what makes the future tenancy migration a change to one
base class rather than an audit of the whole codebase.

The pipeline produces frozen domain objects (SiteSnapshot, Finding,
Opportunity, Scores). This module is the only place that knows how to turn
them into rows and back.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from leadkhojo.core.utils.clock import utcnow
from leadkhojo.crawler.snapshot import SiteSnapshot
from leadkhojo.db.models import (
    Business,
    BusinessScore,
    FindingRecord,
    OpportunityRecord,
    Report,
    Scan,
    SiteSnapshotRecord,
)
from leadkhojo.discovery.providers import DiscoveredBusiness
from leadkhojo.pipeline.runner import BusinessResult


class ScanRepository:
    """Scans, businesses and their analysis output."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- scans -------------------------------------------------------------

    async def create_scan(
        self,
        *,
        keyword: str | None,
        location: str | None,
        provider: str,
        limit: int,
        rerun_of_id: uuid.UUID | None = None,
    ) -> Scan:
        scan = Scan(
            keyword=keyword,
            location=location,
            provider=provider,
            result_limit=limit,
            status="pending",
            rerun_of_id=rerun_of_id,
        )
        self._session.add(scan)
        await self._session.flush()
        return scan

    async def get_scan(self, scan_id: uuid.UUID) -> Scan | None:
        return await self._session.get(Scan, scan_id)

    async def list_scans(self, *, limit: int = 50, offset: int = 0) -> Sequence[Scan]:
        stmt = select(Scan).order_by(Scan.created_at.desc()).limit(limit).offset(offset)
        return (await self._session.scalars(stmt)).all()

    async def count_scans(self) -> int:
        return int(await self._session.scalar(select(func.count()).select_from(Scan)) or 0)

    async def delete_scan(self, scan_id: uuid.UUID) -> bool:
        """Hard delete. Cascades to everything beneath the scan."""
        result = await self._session.execute(delete(Scan).where(Scan.id == scan_id))
        return bool(result.rowcount)

    async def mark_scan_running(self, scan_id: uuid.UUID, total: int) -> None:
        scan = await self._session.get(Scan, scan_id)
        if scan is None:
            return
        scan.status = "analyzing"
        scan.total_businesses = total
        scan.started_at = scan.started_at or utcnow()

    async def update_progress(
        self, scan_id: uuid.UUID, *, current_business: str | None = None
    ) -> None:
        """Recount from the businesses table rather than incrementing.

        A counter that drifts is worse than one that costs a COUNT: the user
        watches it and notices immediately.
        """
        scan = await self._session.get(Scan, scan_id)
        if scan is None:
            return

        completed = await self._session.scalar(
            select(func.count())
            .select_from(Business)
            .where(Business.scan_id == scan_id, Business.status == "completed")
        )
        failed = await self._session.scalar(
            select(func.count())
            .select_from(Business)
            .where(Business.scan_id == scan_id, Business.status.in_(("failed", "no_website")))
        )
        scan.completed_count = int(completed or 0)
        scan.failed_count = int(failed or 0)
        if current_business is not None:
            scan.current_business = current_business

    async def finish_scan(
        self, scan_id: uuid.UUID, *, status: str = "completed", error: str | None = None
    ) -> None:
        scan = await self._session.get(Scan, scan_id)
        if scan is None:
            return
        scan.status = status
        scan.error_message = error
        scan.current_business = None
        scan.completed_at = utcnow()

    # -- businesses --------------------------------------------------------

    async def add_businesses(
        self, scan_id: uuid.UUID, discovered: Sequence[DiscoveredBusiness]
    ) -> list[Business]:
        rows = [
            Business(
                scan_id=scan_id,
                name=b.name,
                website_url=str(b.website_url) if b.website_url else None,
                domain=str(b.domain) if b.domain else None,
                city=b.city,
                country_code=b.country_code,
                category=b.category,
                address=b.address,
                source_provider=b.source,
                source_external_id=b.source_external_id,
                status="pending" if b.has_website else "no_website",
            )
            for b in discovered
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return rows

    async def get_business(self, business_id: uuid.UUID) -> Business | None:
        stmt = (
            select(Business)
            .where(Business.id == business_id)
            .options(
                selectinload(Business.findings),
                selectinload(Business.opportunities),
                selectinload(Business.scores),
                selectinload(Business.snapshot),
            )
        )
        return await self._session.scalar(stmt)

    async def list_businesses(
        self,
        scan_id: uuid.UUID,
        *,
        sort: str = "opportunity_score",
        order: str = "desc",
        status: str | None = "completed",
        has_contact: bool | None = None,
        min_opportunity_score: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Business]:
        stmt = (
            select(Business)
            .where(Business.scan_id == scan_id)
            .options(selectinload(Business.scores), selectinload(Business.opportunities))
        )

        if status and status != "all":
            stmt = stmt.where(Business.status == status)
        if has_contact is True:
            stmt = stmt.where(Business.primary_email.isnot(None))
        elif has_contact is False:
            stmt = stmt.where(Business.primary_email.is_(None))

        score_columns = {
            "opportunity_score": BusinessScore.opportunity_score,
            "lead_score": BusinessScore.lead_score,
            "security_score": BusinessScore.security_score,
            "website_score": BusinessScore.website_score,
        }

        if sort in score_columns:
            column = score_columns[sort]
            stmt = stmt.outerjoin(BusinessScore, BusinessScore.business_id == Business.id)
            if min_opportunity_score is not None:
                stmt = stmt.where(BusinessScore.opportunity_score >= min_opportunity_score)
            stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())
        else:
            column = Business.name  # type: ignore[assignment]
            stmt = stmt.order_by(column.desc() if order == "desc" else column.asc())

        return (await self._session.scalars(stmt.limit(limit).offset(offset))).all()

    async def count_businesses(self, scan_id: uuid.UUID, *, status: str | None = None) -> int:
        stmt = select(func.count()).select_from(Business).where(Business.scan_id == scan_id)
        if status and status != "all":
            stmt = stmt.where(Business.status == status)
        return int(await self._session.scalar(stmt) or 0)

    # -- analysis output ---------------------------------------------------

    async def save_result(self, business_id: uuid.UUID, result: BusinessResult) -> None:
        """Persist one analysed business.

        Replaces any prior analysis for this business, so re-analysis is
        idempotent — running it twice leaves the same rows, not duplicates.
        """
        business = await self._session.get(Business, business_id)
        if business is None:
            return

        await self._clear_analysis(business_id)

        contacts = result.artifact("contacts", "contacts", []) or []
        business.primary_email = result.artifact("contacts", "primary_email")
        business.primary_phone = result.artifact("contacts", "primary_phone")
        business.contacts = list(contacts)
        business.technologies = list(result.artifact("technologies", "technologies", []) or [])
        artifacts = _json_safe(result.artifacts)
        # Precompute severity counts so the results list can render them
        # without eager-loading findings — a 100-row page would otherwise
        # fan out into 100 extra queries.
        artifacts["_finding_counts"] = _severity_counts(result)
        business.artifacts = artifacts
        business.duration_ms = result.duration_ms
        business.analyzed_at = utcnow()

        if result.snapshot is not None:
            snapshot = result.snapshot
            business.final_url = snapshot.final_url
            business.crawled_at = snapshot.captured_at
            business.failure_reason = (
                snapshot.failure_reason.value if snapshot.failure_reason else None
            )
            business.failure_detail = snapshot.failure_detail
            self._session.add(_snapshot_record(business_id, snapshot))

        business.status = "completed" if result.ok else "failed"
        if not result.ok and result.error and business.failure_detail is None:
            business.failure_detail = result.error

        self._session.add_all(
            FindingRecord(
                business_id=business_id,
                check_id=str(f.check_id),
                plugin_id=str(f.plugin_id),
                category=f.category,
                status=f.status.value,
                severity=f.severity.value,
                title=f.title,
                description=f.description,
                evidence=_json_safe(f.evidence) or {"recorded": True},
                remediation=f.remediation,
            )
            for f in result.findings
        )

        self._session.add_all(
            OpportunityRecord(
                business_id=business_id,
                rule_id=str(o.rule_id),
                title=o.title,
                category=o.category.value,
                urgency=o.urgency.value,
                description=o.description,
                description_ai=o.description_ai,
                pitch_angle=o.pitch_angle,
                evidence=_json_safe(o.evidence),
                triggered_by=list(o.triggered_by),
            )
            for o in result.opportunities
        )

        if result.scores is not None:
            self._session.add(
                BusinessScore(
                    business_id=business_id,
                    lead_score=result.scores.lead.total,
                    website_score=result.scores.website.total,
                    security_score=result.scores.security.total,
                    opportunity_score=result.scores.opportunity.total,
                    breakdowns=result.scores.to_dict(),
                )
            )

        await self._session.flush()

    async def _clear_analysis(self, business_id: uuid.UUID) -> None:
        for model in (FindingRecord, OpportunityRecord):
            await self._session.execute(delete(model).where(model.business_id == business_id))
        await self._session.execute(
            delete(BusinessScore).where(BusinessScore.business_id == business_id)
        )
        await self._session.execute(
            delete(SiteSnapshotRecord).where(SiteSnapshotRecord.business_id == business_id)
        )

    async def load_snapshot(self, business_id: uuid.UUID) -> SiteSnapshot | None:
        """Rehydrate a stored snapshot so analysis can re-run without a crawl.

        This is the payoff of crawl-once/analyze-many: improve a rule, re-run
        against stored data, never touch the website again.
        """
        record = await self._session.scalar(
            select(SiteSnapshotRecord).where(SiteSnapshotRecord.business_id == business_id)
        )
        if record is None:
            return None
        return SiteSnapshot.from_dict(dict(record.payload))

    # -- reports -----------------------------------------------------------

    async def record_report(
        self,
        *,
        scan_id: uuid.UUID,
        kind: str,
        filename: str,
        content_type: str,
        size_bytes: int,
        business_id: uuid.UUID | None = None,
    ) -> Report:
        report = Report(
            scan_id=scan_id,
            business_id=business_id,
            kind=kind,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        self._session.add(report)
        await self._session.flush()
        return report

    async def list_reports(self, scan_id: uuid.UUID) -> Sequence[Report]:
        stmt = select(Report).where(Report.scan_id == scan_id).order_by(Report.created_at.desc())
        return (await self._session.scalars(stmt)).all()

    # -- history and comparison -------------------------------------------

    async def business_summaries(self, scan_id: uuid.UUID) -> dict[str, dict[str, Any]]:
        """Domain -> summary, for comparing one scan against another."""
        stmt = (
            select(Business)
            .where(Business.scan_id == scan_id, Business.domain.isnot(None))
            .options(selectinload(Business.scores), selectinload(Business.opportunities))
        )
        rows = (await self._session.scalars(stmt)).all()
        return {
            str(b.domain): {
                "business_id": str(b.id),
                "name": b.name,
                "status": b.status,
                "primary_email": b.primary_email,
                "scores": {
                    "lead": b.scores.lead_score if b.scores else None,
                    "website": b.scores.website_score if b.scores else None,
                    "security": b.scores.security_score if b.scores else None,
                    "opportunity": b.scores.opportunity_score if b.scores else None,
                },
                "opportunity_rule_ids": sorted(o.rule_id for o in b.opportunities),
                "technologies": sorted(
                    str(t.get("name")) for t in (b.technologies or []) if t.get("name")
                ),
            }
            for b in rows
        }


def _snapshot_record(business_id: uuid.UUID, snapshot: SiteSnapshot) -> SiteSnapshotRecord:
    return SiteSnapshotRecord(
        business_id=business_id,
        status=snapshot.status.value,
        render_mode=snapshot.render_mode.value,
        final_url=snapshot.final_url,
        http_status=snapshot.http_status,
        failure_reason=snapshot.failure_reason.value if snapshot.failure_reason else None,
        payload=snapshot.to_dict(),
        page_count=len(snapshot.pages),
        total_bytes=snapshot.total_bytes,
        duration_ms=snapshot.duration_ms,
        captured_at=snapshot.captured_at,
    )


def _severity_counts(result: BusinessResult) -> dict[str, int]:
    """Failing findings by severity. Passing checks are not problems."""
    counts: dict[str, int] = {}
    for finding in result.findings:
        if not finding.is_problem:
            continue
        key = finding.severity.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def _json_safe(value: Any) -> Any:
    """Make a value storable as JSON.

    Evidence dicts can contain datetimes and enums. Serialising them at the
    boundary keeps every plugin free to put whatever is most useful in
    evidence without thinking about the database.
    """
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = ["ScanRepository"]
