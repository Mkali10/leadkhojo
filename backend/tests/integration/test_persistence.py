"""Persistence tests against a real database engine.

Runs on SQLite so the suite needs no service. The schema targets PostgreSQL;
what SQLite cannot exercise is called out in the tests that care.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

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
from leadkhojo.db.models import Business, BusinessScore, FindingRecord, OpportunityRecord, Scan
from leadkhojo.db.repository import ScanRepository
from leadkhojo.discovery.providers import DiscoveredBusiness
from leadkhojo.opportunities.schemas import Opportunity
from leadkhojo.pipeline.runner import BusinessResult
from leadkhojo.scoring.engine import compute_scores
from tests.conftest import make_dns, make_snapshot, make_tls

pytestmark = pytest.mark.asyncio


def _discovered(name: str = "Acme", domain: str = "acme.com") -> DiscoveredBusiness:
    return DiscoveredBusiness(
        name=name,
        website_url=f"https://{domain}",  # type: ignore[arg-type]
        domain=Domain(domain),
        city="Austin",
        country_code="US",
    )


def _result(business: DiscoveredBusiness, *, ok: bool = True) -> BusinessResult:
    if not ok:
        return BusinessResult(business=business, error="No website to analyze")

    findings = (
        Finding(
            check_id=CheckId("TLS-04"),
            plugin_id=PluginId("ssl"),
            category="tls",
            status=FindingStatus.FAIL,
            severity=Severity.HIGH,
            title="SSL certificate expires soon",
            description="Expires in 9 days.",
            evidence={"days_remaining": 9},
            remediation="Renew it.",
        ),
    )
    opportunities = (
        Opportunity(
            rule_id=RuleId("ssl_renewal"),
            title="SSL certificate expires in 9 days",
            category=OpportunityCategory.SECURITY,
            urgency=Urgency.CRITICAL,
            description="Deterministic description.",
            pitch_angle="Lead with the date.",
            evidence={"days_remaining": 9},
            triggered_by=("TLS-04",),
        ),
    )
    artifacts = {
        "contacts": {
            "primary_email": "info@acme.com",
            "primary_phone": "+15125550142",
            "contacts": [{"kind": "email", "value": "info@acme.com", "source_url": "x"}],
        },
        "technologies": {"technologies": [{"id": "wordpress", "name": "WordPress"}]},
    }
    return BusinessResult(
        business=business,
        snapshot=make_snapshot(tls=make_tls(days_until_expiry=9), dns=make_dns()),
        findings=findings,
        opportunities=opportunities,
        artifacts=artifacts,
        scores=compute_scores(findings, opportunities, artifacts),
        duration_ms=1234,
    )


# ---------------------------------------------------------------- scans


async def test_a_scan_round_trips(session) -> None:  # type: ignore[no-untyped-def]
    repo = ScanRepository(session)
    scan = await repo.create_scan(
        keyword="dental clinics", location="Austin, TX", provider="csv_import", limit=25
    )

    loaded = await repo.get_scan(scan.id)

    assert loaded is not None
    assert loaded.keyword == "dental clinics"
    assert loaded.status == "pending"
    assert loaded.percent_complete == 0


async def test_progress_is_recounted_from_reality_not_incremented(session) -> None:  # type: ignore[no-untyped-def]
    """A drifting counter is worse than one that costs a COUNT — the user
    is watching it."""
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    businesses = await repo.add_businesses(
        scan.id, [_discovered("A", "a.com"), _discovered("B", "b.com")]
    )
    await repo.mark_scan_running(scan.id, total=2)

    await repo.save_result(businesses[0].id, _result(_discovered("A", "a.com")))
    await repo.update_progress(scan.id, current_business="A")

    loaded = await repo.get_scan(scan.id)
    assert loaded is not None
    assert loaded.completed_count == 1
    assert loaded.percent_complete == 50
    assert loaded.current_business == "A"


async def test_finishing_a_scan_clears_the_current_business(session) -> None:  # type: ignore[no-untyped-def]
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    await repo.update_progress(scan.id, current_business="Acme")

    await repo.finish_scan(scan.id)

    loaded = await repo.get_scan(scan.id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.current_business is None
    assert loaded.completed_at is not None
    assert loaded.is_terminal


# ---------------------------------------------------------------- businesses


async def test_duplicate_domains_within_a_scan_are_rejected(session) -> None:  # type: ignore[no-untyped-def]
    """The deduplication guarantee, enforced by the database rather than by
    remembering to check."""
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    await repo.add_businesses(scan.id, [_discovered("A", "acme.com")])

    with pytest.raises(IntegrityError):
        await repo.add_businesses(scan.id, [_discovered("A again", "acme.com")])


async def test_the_same_domain_may_appear_in_different_scans(session) -> None:  # type: ignore[no-untyped-def]
    """Otherwise re-running a scan would be impossible."""
    repo = ScanRepository(session)
    first = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    second = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)

    await repo.add_businesses(first.id, [_discovered()])
    await repo.add_businesses(second.id, [_discovered()])

    assert await repo.count_businesses(first.id, status="all") == 1
    assert await repo.count_businesses(second.id, status="all") == 1


async def test_businesses_without_a_website_are_recorded_not_dropped(session) -> None:  # type: ignore[no-untyped-def]
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)

    await repo.add_businesses(
        scan.id, [DiscoveredBusiness(name="No Site", website_url=None, domain=None)]
    )

    rows = await repo.list_businesses(scan.id, status="all")
    assert len(rows) == 1
    assert rows[0].status == "no_website"


# ---------------------------------------------------------------- results


async def test_a_full_result_is_persisted(session) -> None:  # type: ignore[no-untyped-def]
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    business = (await repo.add_businesses(scan.id, [_discovered()]))[0]

    await repo.save_result(business.id, _result(_discovered()))

    loaded = await repo.get_business(business.id)
    assert loaded is not None
    assert loaded.status == "completed"
    assert loaded.primary_email == "info@acme.com"
    assert len(loaded.findings) == 1
    assert len(loaded.opportunities) == 1
    assert loaded.scores is not None
    assert loaded.snapshot is not None
    assert loaded.findings[0].evidence["days_remaining"] == 9


async def test_the_deterministic_description_is_stored_separately_from_any_rewrite(
    session,  # type: ignore[no-untyped-def]
) -> None:
    """description is the source of truth; description_ai never replaces it."""
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    business = (await repo.add_businesses(scan.id, [_discovered()]))[0]

    await repo.save_result(business.id, _result(_discovered()))

    loaded = await repo.get_business(business.id)
    assert loaded is not None
    opportunity = loaded.opportunities[0]
    assert opportunity.description == "Deterministic description."
    assert opportunity.description_ai is None


async def test_re_saving_replaces_rather_than_duplicates(session) -> None:  # type: ignore[no-untyped-def]
    """Re-analysis must be idempotent, or a re-run doubles every finding."""
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    business = (await repo.add_businesses(scan.id, [_discovered()]))[0]

    await repo.save_result(business.id, _result(_discovered()))
    await repo.save_result(business.id, _result(_discovered()))

    loaded = await repo.get_business(business.id)
    assert loaded is not None
    assert len(loaded.findings) == 1
    assert len(loaded.opportunities) == 1


async def test_a_failed_business_is_recorded_with_its_reason(session) -> None:  # type: ignore[no-untyped-def]
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    business = (await repo.add_businesses(scan.id, [_discovered()]))[0]

    await repo.save_result(business.id, _result(_discovered(), ok=False))

    loaded = await repo.get_business(business.id)
    assert loaded is not None
    assert loaded.status == "failed"
    assert loaded.failure_detail


async def test_a_stored_snapshot_rehydrates_for_re_analysis(session) -> None:  # type: ignore[no-untyped-def]
    """The payoff of crawl-once/analyze-many: improve a rule, re-run against
    stored data, never touch the website again."""
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    business = (await repo.add_businesses(scan.id, [_discovered()]))[0]
    await repo.save_result(business.id, _result(_discovered()))

    snapshot = await repo.load_snapshot(business.id)

    assert snapshot is not None
    assert snapshot.domain == "acme.com"
    assert snapshot.tls is not None
    assert snapshot.dns is not None


# ---------------------------------------------------------------- querying


async def test_results_sort_by_any_score(session) -> None:  # type: ignore[no-untyped-def]
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    rows = await repo.add_businesses(
        scan.id, [_discovered("Low", "low.com"), _discovered("High", "high.com")]
    )

    await repo.save_result(rows[0].id, _result(_discovered("Low", "low.com")))
    await repo.save_result(rows[1].id, _result(_discovered("High", "high.com")))
    # Make the ordering unambiguous.
    (await repo.get_business(rows[1].id)).scores.opportunity_score = 99  # type: ignore[union-attr]
    (await repo.get_business(rows[0].id)).scores.opportunity_score = 10  # type: ignore[union-attr]
    await session.flush()

    ranked = await repo.list_businesses(scan.id, sort="opportunity_score", order="desc")
    assert [b.name for b in ranked] == ["High", "Low"]


async def test_results_filter_by_contact_availability(session) -> None:  # type: ignore[no-untyped-def]
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    rows = await repo.add_businesses(
        scan.id, [_discovered("With", "with.com"), _discovered("Without", "without.com")]
    )
    await repo.save_result(rows[0].id, _result(_discovered("With", "with.com")))

    no_contact = _result(_discovered("Without", "without.com"))
    no_contact.artifacts["contacts"] = {"primary_email": None, "contacts": []}
    await repo.save_result(rows[1].id, no_contact)

    with_contact = await repo.list_businesses(scan.id, has_contact=True)
    assert [b.name for b in with_contact] == ["With"]


# ---------------------------------------------------------------- deletion


async def test_deleting_a_scan_removes_everything_beneath_it(session) -> None:  # type: ignore[no-untyped-def]
    """A scan the user deleted should actually be gone."""
    from sqlalchemy import func, select

    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    business = (await repo.add_businesses(scan.id, [_discovered()]))[0]
    await repo.save_result(business.id, _result(_discovered()))

    await repo.delete_scan(scan.id)
    await session.flush()

    for model in (Scan, Business, FindingRecord, OpportunityRecord, BusinessScore):
        remaining = await session.scalar(select(func.count()).select_from(model))
        assert remaining == 0, f"{model.__name__} rows survived the cascade"


async def test_deleting_a_missing_scan_is_not_an_error(session) -> None:  # type: ignore[no-untyped-def]
    repo = ScanRepository(session)
    assert await repo.delete_scan(uuid.uuid4()) is False


# ---------------------------------------------------------------- comparison


async def test_summaries_are_keyed_by_domain_for_comparison(session) -> None:  # type: ignore[no-untyped-def]
    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="csv_import", limit=25)
    business = (await repo.add_businesses(scan.id, [_discovered()]))[0]
    await repo.save_result(business.id, _result(_discovered()))

    summaries = await repo.business_summaries(scan.id)

    assert "acme.com" in summaries
    assert summaries["acme.com"]["opportunity_rule_ids"] == ["ssl_renewal"]
    assert summaries["acme.com"]["scores"]["opportunity"] is not None
