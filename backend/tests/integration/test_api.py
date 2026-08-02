"""API tests.

Exercised through the real ASGI app, a real database and the real job queue.
The only thing replaced is the crawler: the network is the one dependency a
test suite must never have, and stubbing it here is legitimate precisely
because the crawler is the sole component that touches it.

Workers are driven explicitly with `drain()` rather than left polling in the
background, so every assertion runs against a settled state instead of racing
a poll interval.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from leadkhojo.api import deps
from leadkhojo.api.app import create_app
from leadkhojo.core.types import Domain, SnapshotStatus, Url
from leadkhojo.crawler.snapshot import SiteSnapshot
from leadkhojo.jobs.worker import WorkerPool
from leadkhojo.plugins.registry import build_engine
from tests.conftest import FIXED_NOW, make_page, make_tls

pytestmark = pytest.mark.asyncio

API = "/api/v1"

# A page with a real contact on it, and one without. The second is what
# proves the no-synthesis rule survives to the wire: no info@ fallback.
_WITH_CONTACT = """
<html><body>
  <h1>Acme Dental</h1>
  <a href="mailto:hello@{domain}">Email us</a>
</body></html>
"""
_WITHOUT_CONTACT = "<html><body><h1>Quiet Co</h1><p>No way to reach us.</p></body></html>"


class _StubCrawler:
    """Stands in for CrawlerService. Same shape, no sockets."""

    def __init__(self, settings: object) -> None:
        self._settings = settings

    async def crawl(self, url: str, *, now: object = None) -> SiteSnapshot:
        domain = url.replace("https://", "").replace("http://", "").strip("/")
        html = (
            _WITHOUT_CONTACT
            if domain.startswith("nocontact")
            else _WITH_CONTACT.format(domain=domain)
        )
        return SiteSnapshot(
            domain=Domain(domain),
            requested_url=Url(url),
            final_url=Url(url),
            status=SnapshotStatus.COMPLETE,
            captured_at=FIXED_NOW,
            http_status=200,
            pages=(make_page(url, html=html),),
            # A certificate close to expiry, so the run produces findings and
            # opportunities rather than an empty happy path.
            tls=make_tls(days_until_expiry=9),
        )


@pytest_asyncio.fixture
async def client(engine, test_settings, rules_dir, monkeypatch) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    from leadkhojo.jobs import handlers

    monkeypatch.setattr(handlers, "CrawlerService", _StubCrawler)

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    plugin_engine = build_engine(rules_dir)
    deps.set_plugin_engine(plugin_engine)
    deps.set_worker_pool(
        WorkerPool(settings=test_settings, sessionmaker=factory, engine=plugin_engine)
    )

    async def _override() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # ASGITransport does not run the lifespan, so nothing here fights the
    # singletons set above.
    app = create_app(test_settings)
    app.dependency_overrides[deps.get_db_session] = _override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http

    deps.set_plugin_engine(None)
    deps.set_worker_pool(None)


async def _drain(budget_seconds: float = 30.0) -> int:
    pool = deps.get_worker_pool()
    assert pool is not None
    return await pool.drain(timeout=budget_seconds)


async def _scan_from_csv(client: AsyncClient, csv: str = "domain\nacme.com\n") -> str:
    files = {"file": ("domains.csv", csv.encode(), "text/csv")}
    response = await client.post(f"{API}/scans/csv", files=files)
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


async def _completed_scan(client: AsyncClient, csv: str = "domain\nacme.com\n") -> str:
    scan_id = await _scan_from_csv(client, csv)
    await _drain()
    return scan_id


# ================================================================ health


async def test_liveness_reports_ok(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_liveness_checks_no_dependency(client: AsyncClient) -> None:
    """If it did, a brief database blip would make the orchestrator kill
    every healthy container at once."""
    response = await client.get("/healthz")

    assert response.status_code == 200
    assert "database" not in response.json()


async def test_readiness_reports_dependencies(client: AsyncClient) -> None:
    response = await client.get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["database"] is True
    assert payload["plugins"] > 0


async def test_every_response_carries_a_correlation_id(client: AsyncClient) -> None:
    assert (await client.get("/healthz")).headers["X-Correlation-Id"]


async def test_a_supplied_correlation_id_is_echoed(client: AsyncClient) -> None:
    """So a user's bug report and the server log share one identifier."""
    response = await client.get("/healthz", headers={"X-Correlation-Id": "abc-123"})

    assert response.headers["X-Correlation-Id"] == "abc-123"


async def test_security_headers_are_set(client: AsyncClient) -> None:
    response = await client.get("/healthz")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


# ================================================================ openapi


async def test_the_openapi_document_is_served(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "LeadKhojo API"
    assert "/api/v1/scans" in spec["paths"]
    assert "/api/v1/scans/{scan_id}/progress" in spec["paths"]


async def test_the_docs_page_renders(client: AsyncClient) -> None:
    assert (await client.get("/docs")).status_code == 200


# ================================================================ scans


async def test_creating_a_scan_returns_202_and_an_id(client: AsyncClient) -> None:
    """202, not 201: the work is accepted, not finished."""
    response = await client.post(f"{API}/scans", json={"urls": ["acme.com"]})

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "pending"
    assert uuid.UUID(payload["id"])


async def test_a_scan_with_neither_urls_nor_keyword_is_rejected(
    client: AsyncClient,
) -> None:
    response = await client.post(f"{API}/scans", json={})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_an_out_of_range_limit_reports_the_field(client: AsyncClient) -> None:
    """Every invalid field at once, named — not one per round trip."""
    response = await client.post(f"{API}/scans", json={"urls": ["a.com"], "limit": 9999})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert any("limit" in error["field"] for error in body["errors"])


async def test_progress_is_pollable_immediately(client: AsyncClient) -> None:
    scan_id = (await client.post(f"{API}/scans", json={"urls": ["acme.com"]})).json()["id"]

    response = await client.get(f"{API}/scans/{scan_id}/progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["percent_complete"] == 0


async def test_progress_reaches_100_when_the_scan_finishes(client: AsyncClient) -> None:
    scan_id = await _completed_scan(client, "domain\na.com\nb.com\n")

    payload = (await client.get(f"{API}/scans/{scan_id}/progress")).json()

    assert payload["status"] == "completed"
    assert payload["percent_complete"] == 100
    assert payload["elapsed_seconds"] is not None


async def test_an_unknown_scan_returns_a_problem_document(client: AsyncClient) -> None:
    response = await client.get(f"{API}/scans/{uuid.uuid4()}")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["detail"]
    assert body["correlation_id"]


async def test_a_malformed_uuid_is_a_validation_error_not_a_crash(
    client: AsyncClient,
) -> None:
    assert (await client.get(f"{API}/scans/not-a-uuid")).status_code == 422


async def test_scan_history_is_listed(client: AsyncClient) -> None:
    await client.post(f"{API}/scans", json={"urls": ["first.com"]})
    await client.post(f"{API}/scans", json={"urls": ["second.com"]})

    response = await client.get(f"{API}/scans")

    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total"] == 2
    assert len(body["data"]) == 2


async def test_a_scan_can_be_cancelled(client: AsyncClient) -> None:
    scan_id = (await client.post(f"{API}/scans", json={"urls": ["acme.com"]})).json()["id"]

    response = await client.post(f"{API}/scans/{scan_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_cancelling_drops_the_queued_work(client: AsyncClient) -> None:
    """A cancel that leaves jobs running is not a cancel."""
    scan_id = await _scan_from_csv(client, "domain\na.com\nb.com\n")
    await client.post(f"{API}/scans/{scan_id}/cancel")

    assert await _drain() == 0


async def test_cancelling_a_finished_scan_conflicts(client: AsyncClient) -> None:
    scan_id = (await client.post(f"{API}/scans", json={"urls": ["acme.com"]})).json()["id"]
    await client.post(f"{API}/scans/{scan_id}/cancel")

    response = await client.post(f"{API}/scans/{scan_id}/cancel")

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_deleting_a_scan_removes_it(client: AsyncClient) -> None:
    scan_id = await _completed_scan(client)

    assert (await client.delete(f"{API}/scans/{scan_id}")).status_code == 204
    assert (await client.get(f"{API}/scans/{scan_id}")).status_code == 404


# ================================================================ csv upload


async def test_a_csv_upload_creates_a_scan(client: AsyncClient) -> None:
    files = {"file": ("domains.csv", b"domain\nacme.com\nbeta.com\n", "text/csv")}

    response = await client.post(f"{API}/scans/csv", files=files)

    assert response.status_code == 202
    assert response.json()["provider"] == "csv_import"


async def test_a_csv_without_a_domain_column_is_rejected_at_upload(
    client: AsyncClient,
) -> None:
    """Rejected here, with a usable message, rather than inside a worker
    where the user cannot see it."""
    files = {"file": ("bad.csv", b"company,town\nAcme,Austin\n", "text/csv")}

    response = await client.post(f"{API}/scans/csv", files=files)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_csv"
    assert "domain" in body["detail"].lower()


async def test_csv_validation_reports_without_creating_anything(
    client: AsyncClient,
) -> None:
    """So nobody uploads 400 rows and finds out afterwards."""
    files = {"file": ("d.csv", b"domain,name\nacme.com,Acme\n,Nameless\n", "text/csv")}

    response = await client.post(f"{API}/scans/csv/validate", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    assert body["valid_row_count"] == 1
    assert body["invalid_rows"] == [{"row": 2, "reason": "empty domain"}]
    assert (await client.get(f"{API}/scans")).json()["pagination"]["total"] == 0


# ================================================================ results


async def test_results_are_listed_once_a_scan_runs(client: AsyncClient) -> None:
    scan_id = await _completed_scan(client)

    response = await client.get(f"{API}/scans/{scan_id}/businesses")

    assert response.status_code == 200
    body = response.json()
    assert body["scan_status"] == "completed"
    assert [row["domain"] for row in body["data"]] == ["acme.com"]


async def test_a_result_row_carries_everything_the_table_needs(
    client: AsyncClient,
) -> None:
    """The table renders from this alone — no follow-up request per row."""
    scan_id = await _completed_scan(client)

    row = (await client.get(f"{API}/scans/{scan_id}/businesses")).json()["data"][0]

    for field in (
        "scores",
        "primary_email",
        "contact_count",
        "opportunity_count",
        "top_opportunity",
        "top_technologies",
        "critical_findings",
    ):
        assert field in row, f"{field} missing from the results row"
    assert row["scores"]["opportunity"] is not None


async def test_a_contact_found_on_the_site_reaches_the_wire(
    client: AsyncClient,
) -> None:
    scan_id = await _completed_scan(client)

    row = (await client.get(f"{API}/scans/{scan_id}/businesses")).json()["data"][0]

    assert row["primary_email"] == "hello@acme.com"


async def test_a_business_with_no_contact_returns_null_not_a_guess(
    client: AsyncClient,
) -> None:
    """The no-synthesis rule holds all the way out to the client: no
    info@domain fallback, ever."""
    scan_id = await _completed_scan(client, "domain\nnocontact.com\n")

    row = (await client.get(f"{API}/scans/{scan_id}/businesses")).json()["data"][0]

    assert row["primary_email"] is None
    assert "info@nocontact.com" not in str(row)


async def test_results_can_be_filtered_to_businesses_with_a_contact(
    client: AsyncClient,
) -> None:
    scan_id = await _completed_scan(client, "domain\nacme.com\nnocontact.com\n")

    with_contact = await client.get(f"{API}/scans/{scan_id}/businesses?has_contact=true")
    without = await client.get(f"{API}/scans/{scan_id}/businesses?has_contact=false")

    assert [r["domain"] for r in with_contact.json()["data"]] == ["acme.com"]
    assert [r["domain"] for r in without.json()["data"]] == ["nocontact.com"]


async def test_results_are_paginated(client: AsyncClient) -> None:
    scan_id = await _completed_scan(client, "domain\na.com\nb.com\nc.com\n")

    body = (await client.get(f"{API}/scans/{scan_id}/businesses?limit=2")).json()

    assert len(body["data"]) == 2
    assert body["pagination"] == {"total": 3, "limit": 2, "offset": 0}


async def test_business_detail_returns_findings_and_opportunities(
    client: AsyncClient,
) -> None:
    scan_id = await _completed_scan(client)
    business_id = (await client.get(f"{API}/scans/{scan_id}/businesses")).json()["data"][0]["id"]

    response = await client.get(f"{API}/businesses/{business_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["findings"]
    assert detail["opportunities"]
    assert detail["contacts"]
    assert detail["snapshot"]["page_count"] == 1


async def test_every_finding_carries_evidence(client: AsyncClient) -> None:
    """The rule the whole product rests on. An unevidenced claim made to a
    prospect is worse than saying nothing."""
    scan_id = await _completed_scan(client)
    business_id = (await client.get(f"{API}/scans/{scan_id}/businesses")).json()["data"][0]["id"]

    detail = (await client.get(f"{API}/businesses/{business_id}")).json()

    problems = [f for f in detail["findings"] if f["status"] in ("fail", "warn")]
    assert problems
    assert all(f["evidence"] for f in problems)


async def test_the_deterministic_description_is_never_replaced_by_ai(
    client: AsyncClient,
) -> None:
    """`description` is the rule engine's output and the source of truth;
    any rewrite lands in `description_ai` beside it, never over it."""
    scan_id = await _completed_scan(client)
    business_id = (await client.get(f"{API}/scans/{scan_id}/businesses")).json()["data"][0]["id"]

    detail = (await client.get(f"{API}/businesses/{business_id}")).json()

    for opportunity in detail["opportunities"]:
        assert opportunity["description"]
        assert opportunity["description_ai"] is None  # NullRewriter in v1


async def test_an_unknown_business_returns_404(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/businesses/{uuid.uuid4()}")).status_code == 404


# ================================================================ exports


async def test_csv_export_returns_a_downloadable_file(client: AsyncClient) -> None:
    scan_id = await _completed_scan(client)

    response = await client.get(f"{API}/exports/scans/{scan_id}/csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM, so Excel behaves
    assert b"acme.com" in response.content


async def test_scan_pdf_export_returns_a_pdf(client: AsyncClient) -> None:
    scan_id = await _completed_scan(client)

    response = await client.get(f"{API}/exports/scans/{scan_id}/pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


async def test_business_pdf_export_returns_a_pdf(client: AsyncClient) -> None:
    scan_id = await _completed_scan(client)
    business_id = (await client.get(f"{API}/scans/{scan_id}/businesses")).json()["data"][0]["id"]

    response = await client.get(f"{API}/exports/businesses/{business_id}/pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


async def test_exporting_an_unknown_scan_returns_404(client: AsyncClient) -> None:
    assert (await client.get(f"{API}/exports/scans/{uuid.uuid4()}/csv")).status_code == 404


# ================================================================ meta


async def test_the_plugin_catalogue_is_introspectable(client: AsyncClient) -> None:
    """Makes 'do you detect Craft CMS?' answerable with a URL."""
    response = await client.get(f"{API}/meta/plugins")

    assert response.status_code == 200
    plugins = response.json()
    ids = [p["id"] for p in plugins]
    assert "ssl" in ids
    assert "opportunities" in ids
    # Declared dependencies are visible, so the execution order is explicable.
    cms = next(p for p in plugins if p["id"] == "cms")
    assert cms["depends_on"] == ["technologies"]
    assert ids.index("technologies") < ids.index("cms")
