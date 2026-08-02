"""HTTP routes.

Thin by design: parse, call the service, serialize. No business logic here.

There is NO authentication in v1. That is a deliberate scope decision, and
it carries an operational obligation — do not expose an instance to the
internet. The app logs a warning at startup when it binds publicly.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from leadkhojo import __version__
from leadkhojo.api import schemas
from leadkhojo.api.deps import (
    SettingsDep,
    get_db_session,
    get_plugin_engine,
    get_scan_service,
    get_worker_pool,
)
from leadkhojo.api.service import ScanService
from leadkhojo.core.errors import InvalidCsvError, NotFoundError
from leadkhojo.db.repository import ScanRepository
from leadkhojo.discovery.providers import MAX_BYTES, MAX_ROWS, CsvImportProvider
from leadkhojo.export.csv_writer import write_csv
from leadkhojo.export.pdf_report import build_business_report, build_scan_summary
from leadkhojo.plugins.engine import PluginEngine

ServiceDep = Annotated[ScanService, Depends(get_scan_service)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]

health_router = APIRouter(tags=["health"])
scans_router = APIRouter(prefix="/scans", tags=["scans"])
businesses_router = APIRouter(prefix="/businesses", tags=["businesses"])
exports_router = APIRouter(prefix="/exports", tags=["exports"])
meta_router = APIRouter(prefix="/meta", tags=["meta"])


# ================================================================ health


@health_router.get("/healthz", response_model=schemas.HealthResponse)
async def liveness() -> schemas.HealthResponse:
    """Is the process up?

    Deliberately checks no dependency. If it did, a brief database blip
    would make the orchestrator kill every healthy container at once —
    turning a degradation into an outage.
    """
    return schemas.HealthResponse(status="ok", version=__version__)


@health_router.get("/readyz", response_model=schemas.ReadinessResponse)
async def readiness(
    session: SessionDep,
    engine: Annotated[PluginEngine, Depends(get_plugin_engine)],
    response: Response,
) -> schemas.ReadinessResponse:
    """Can we actually serve traffic? This one does check dependencies."""
    database_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        # The answer readiness needs is the boolean, not the traceback.
        database_ok = False

    plugins = len(engine.plugin_ids)
    pool = get_worker_pool()
    ready = database_ok and plugins > 0

    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return schemas.ReadinessResponse(
        status="ready" if ready else "degraded",
        database=database_ok,
        rules_loaded=plugins > 0,
        plugins=plugins,
        workers_running=bool(pool and pool.running),
    )


# ================================================================ scans


@scans_router.post(
    "",
    response_model=schemas.ScanSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a scan",
)
async def create_scan(
    request: schemas.CreateScanRequest, service: ServiceDep
) -> schemas.ScanSummary:
    """Queue a scan and return immediately.

    202, not 201: the work has been accepted, not completed. Poll
    /scans/{id}/progress to follow it.
    """
    scan = await service.create_scan(request)
    return schemas.ScanSummary.model_validate(scan)


@scans_router.post(
    "/csv",
    response_model=schemas.ScanSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a scan from an uploaded CSV",
)
async def create_scan_from_csv(
    service: ServiceDep,
    file: Annotated[UploadFile, File(description="CSV with a domain or website column")],
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = MAX_ROWS,
) -> schemas.ScanSummary:
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise InvalidCsvError(
            f"File is {len(raw) // 1024} KB; the limit is {MAX_BYTES // 1024} KB.",
            meta={"bytes": len(raw), "limit": MAX_BYTES},
        )

    content = raw.decode("utf-8-sig", errors="replace")
    # Parse eagerly so a malformed upload fails here, with row numbers,
    # rather than inside a worker where the user cannot see it.
    CsvImportProvider(content).parse(limit=limit)

    scan = await service.create_scan_from_csv(
        schemas.CreateScanFromCsvRequest(csv_content=content, limit=limit)
    )
    return schemas.ScanSummary.model_validate(scan)


@scans_router.post("/csv/validate", summary="Dry-run a CSV upload")
async def validate_csv(
    file: Annotated[UploadFile, File()],
    limit: Annotated[int, Query(ge=1, le=MAX_ROWS)] = MAX_ROWS,
) -> dict[str, object]:
    """Report what an upload would produce, without creating anything.

    Exists so nobody uploads 400 rows and discovers afterwards that column
    detection went wrong.
    """
    raw = await file.read()
    result = CsvImportProvider(raw).parse(limit=limit)
    return {
        "created": False,
        "valid_row_count": len(result.businesses),
        "invalid_rows": [{"row": e.row, "reason": e.reason} for e in result.errors[:50]],
        "detected_columns": result.detected_columns,
        "preview": [{"name": b.name, "domain": str(b.domain)} for b in result.businesses[:5]],
    }


@scans_router.get("", response_model=schemas.ScanListResponse, summary="Scan history")
async def list_scans(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.ScanListResponse:
    return await service.list_scans(limit=limit, offset=offset)


@scans_router.get("/{scan_id}", response_model=schemas.ScanSummary)
async def get_scan(scan_id: uuid.UUID, service: ServiceDep) -> schemas.ScanSummary:
    return await service.get_scan(scan_id)


@scans_router.get(
    "/{scan_id}/progress",
    response_model=schemas.ScanProgress,
    summary="Live progress (poll this)",
)
async def get_progress(scan_id: uuid.UUID, service: ServiceDep) -> schemas.ScanProgress:
    """Small and cheap: the UI polls this every 2 seconds while a scan runs.

    Stop polling once status is completed, failed or cancelled.
    """
    return await service.get_progress(scan_id)


@scans_router.get(
    "/{scan_id}/businesses",
    response_model=schemas.BusinessListResponse,
    summary="Scan results",
)
async def list_businesses(
    scan_id: uuid.UUID,
    service: ServiceDep,
    sort: Literal[
        "opportunity_score", "lead_score", "security_score", "website_score", "name"
    ] = "opportunity_score",
    order: Literal["asc", "desc"] = "desc",
    status_filter: Annotated[
        Literal["completed", "failed", "no_website", "all"], Query(alias="status")
    ] = "completed",
    has_contact: bool | None = None,
    min_opportunity_score: Annotated[int | None, Query(ge=0, le=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.BusinessListResponse:
    return await service.list_businesses(
        scan_id,
        sort=sort,
        order=order,
        status=status_filter,
        has_contact=has_contact,
        min_opportunity_score=min_opportunity_score,
        limit=limit,
        offset=offset,
    )


@scans_router.post(
    "/{scan_id}/rerun",
    response_model=schemas.ScanSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run a scan against the same targets",
)
async def rerun_scan(scan_id: uuid.UUID, service: ServiceDep) -> schemas.ScanSummary:
    """Creates a NEW scan. Keeping both is what makes comparison possible."""
    scan = await service.rerun_scan(scan_id)
    return schemas.ScanSummary.model_validate(scan)


@scans_router.get(
    "/{scan_id}/compare/{other_scan_id}",
    response_model=schemas.ScanComparison,
    summary="Compare two scans",
)
async def compare_scans(
    scan_id: uuid.UUID, other_scan_id: uuid.UUID, service: ServiceDep
) -> schemas.ScanComparison:
    """What changed between two scans of the same targets."""
    return await service.compare_scans(scan_id, other_scan_id)


@scans_router.post("/{scan_id}/cancel", response_model=schemas.ScanSummary)
async def cancel_scan(scan_id: uuid.UUID, service: ServiceDep) -> schemas.ScanSummary:
    return schemas.ScanSummary.model_validate(await service.cancel_scan(scan_id))


@scans_router.delete("/{scan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scan(scan_id: uuid.UUID, service: ServiceDep) -> Response:
    await service.delete_scan(scan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ================================================================ businesses


@businesses_router.get("/{business_id}", response_model=schemas.BusinessDetail)
async def get_business(business_id: uuid.UUID, service: ServiceDep) -> schemas.BusinessDetail:
    return await service.get_business(business_id)


# ================================================================ exports


@exports_router.get("/scans/{scan_id}/csv", summary="Export results as CSV")
async def export_scan_csv(
    scan_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> Response:
    repo = ScanRepository(session)
    scan = await repo.get_scan(scan_id)
    if scan is None:
        raise NotFoundError(f"No scan with id {scan_id}.")

    results = await _load_results(repo, scan_id, settings.max_businesses_per_scan)
    payload = write_csv(results)
    filename = _filename(scan, "csv")

    await repo.record_report(
        scan_id=scan_id,
        kind="csv",
        filename=filename,
        content_type="text/csv",
        size_bytes=len(payload),
    )

    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@exports_router.get("/scans/{scan_id}/pdf", summary="Export a scan summary PDF")
async def export_scan_pdf(
    scan_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> Response:
    repo = ScanRepository(session)
    scan = await repo.get_scan(scan_id)
    if scan is None:
        raise NotFoundError(f"No scan with id {scan_id}.")

    results = await _load_results(repo, scan_id, settings.max_businesses_per_scan)
    title = scan.keyword or "Scan summary"
    payload = build_scan_summary(results, title=title)
    filename = _filename(scan, "pdf")

    await repo.record_report(
        scan_id=scan_id,
        kind="pdf_summary",
        filename=filename,
        content_type="application/pdf",
        size_bytes=len(payload),
    )

    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@exports_router.get("/businesses/{business_id}/pdf", summary="Export a business report")
async def export_business_pdf(business_id: uuid.UUID, session: SessionDep) -> Response:
    repo = ScanRepository(session)
    business = await repo.get_business(business_id)
    if business is None:
        raise NotFoundError(f"No business with id {business_id}.")

    result = await _to_business_result(repo, business)
    payload = build_business_report(result)
    filename = f"leadkhojo-{(business.domain or 'report').replace('.', '-')}.pdf"

    await repo.record_report(
        scan_id=business.scan_id,
        business_id=business.id,
        kind="pdf_business",
        filename=filename,
        content_type="application/pdf",
        size_bytes=len(payload),
    )

    return Response(
        content=payload,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ================================================================ meta


@meta_router.get("/plugins", response_model=list[schemas.PluginInfo])
async def list_plugins(
    engine: Annotated[PluginEngine, Depends(get_plugin_engine)],
) -> list[schemas.PluginInfo]:
    """Introspect the loaded plugin set and its execution order.

    Makes 'do you detect Craft CMS?' answerable with a URL rather than a
    code read. Reads the loaded engine rather than rebuilding it, so the
    answer reflects what is actually running — disabled plugins included.
    """
    return [
        schemas.PluginInfo(
            id=p.meta.id,
            name=p.meta.name,
            version=p.meta.version,
            kind=p.meta.kind.value,
            depends_on=list(p.meta.depends_on),
            provides=list(p.meta.provides),
        )
        for p in engine.plugins
    ]


# ================================================================ helpers


async def _load_results(repo: ScanRepository, scan_id: uuid.UUID, limit: int) -> list[object]:
    businesses = await repo.list_businesses(scan_id, status="all", limit=limit)
    return [await _to_business_result(repo, b) for b in businesses]


async def _to_business_result(repo: ScanRepository, business: object) -> object:
    """Rebuild the in-memory BusinessResult the exporters expect.

    The exporters were written against the pipeline's domain objects, so
    persistence adapts to them rather than the reverse — one CSV writer
    serves both the CLI and the API.
    """
    from leadkhojo.core.findings import Finding
    from leadkhojo.core.types import (
        CheckId,
        Domain,
        FindingStatus,
        OpportunityCategory,
        PluginId,
        RuleId,
        Severity,
        Urgency,
    )
    from leadkhojo.discovery.providers import DiscoveredBusiness
    from leadkhojo.opportunities.schemas import Opportunity
    from leadkhojo.pipeline.runner import BusinessResult
    from leadkhojo.scoring.engine import ScoreBreakdown, Scores

    loaded = await repo.get_business(business.id)  # type: ignore[attr-defined]
    if loaded is None:  # pragma: no cover - defensive
        raise NotFoundError("Business disappeared mid-export.")

    discovered = DiscoveredBusiness(
        name=loaded.name,
        website_url=loaded.website_url,  # type: ignore[arg-type]
        domain=Domain(loaded.domain) if loaded.domain else None,
        city=loaded.city,
        country_code=loaded.country_code,
        category=loaded.category,
        source=loaded.source_provider,
    )

    findings = tuple(
        Finding(
            check_id=CheckId(f.check_id),
            plugin_id=PluginId(f.plugin_id),
            category=f.category,
            status=FindingStatus(f.status),
            severity=Severity(f.severity),
            title=f.title,
            description=f.description,
            evidence=dict(f.evidence),
            remediation=f.remediation,
        )
        for f in loaded.findings
    )

    opportunities = tuple(
        Opportunity(
            rule_id=RuleId(o.rule_id),
            title=o.title,
            category=OpportunityCategory(o.category),
            urgency=Urgency(o.urgency),
            description=o.description,
            pitch_angle=o.pitch_angle,
            evidence=dict(o.evidence),
            triggered_by=tuple(o.triggered_by or ()),
            description_ai=o.description_ai,
        )
        for o in loaded.opportunities
    )

    scores = None
    if loaded.scores is not None:
        raw = loaded.scores.breakdowns or {}

        def _breakdown(key: str, total: int) -> ScoreBreakdown:
            entry = raw.get(key, {})
            return ScoreBreakdown(
                total=total,
                components=dict(entry.get("components", {})),
                confidence=float(entry.get("confidence", 1.0)),
            )

        scores = Scores(
            lead=_breakdown("lead", loaded.scores.lead_score),
            website=_breakdown("website", loaded.scores.website_score),
            security=_breakdown("security", loaded.scores.security_score),
            opportunity=_breakdown("opportunity", loaded.scores.opportunity_score),
        )

    snapshot = await repo.load_snapshot(loaded.id)

    return BusinessResult(
        business=discovered,
        snapshot=snapshot,
        findings=findings,
        opportunities=opportunities,
        artifacts=dict(loaded.artifacts or {}),
        scores=scores,
        error=loaded.failure_detail,
        duration_ms=loaded.duration_ms,
    )


def _filename(scan: object, extension: str) -> str:
    import re

    keyword = getattr(scan, "keyword", None) or "scan"
    slug = re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-")[:40] or "scan"
    date = getattr(scan, "created_at", None)
    stamp = date.strftime("%Y%m%d") if date else "export"
    return f"leadkhojo-{slug}-{stamp}.{extension}"


__all__ = [
    "businesses_router",
    "exports_router",
    "health_router",
    "meta_router",
    "scans_router",
]
