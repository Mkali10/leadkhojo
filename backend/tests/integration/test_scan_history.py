"""Scan history: re-running a scan, and diffing two of them.

This is what turns a one-off audit into something worth repeating. A single
scan says "this site has no DMARC". Two scans say "their DMARC disappeared
since last month", which is a reason to pick up the phone.

The re-run is deliberately a NEW scan rather than an overwrite: keeping both
is what makes the comparison possible at all.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.integration.conftest import (
    API,
    HEALTHY,
    NEGLECTED,
    drain,
    rows,
    run_scan,
    set_profile,
    start_scan,
)

pytestmark = pytest.mark.asyncio


async def _rerun(client: AsyncClient, scan_id: str) -> str:
    response = await client.post(f"{API}/scans/{scan_id}/rerun")
    assert response.status_code == 202, response.text
    new_id = str(response.json()["id"])
    await drain()
    return new_id


async def _compare(client: AsyncClient, before: str, after: str) -> dict:
    response = await client.get(f"{API}/scans/{before}/compare/{after}")
    assert response.status_code == 200, response.text
    return dict(response.json())


def _for(comparison: dict, domain: str) -> dict:
    return next(b for b in comparison["businesses"] if b["domain"] == domain)


# ================================================================ re-running


async def test_a_rerun_creates_a_new_scan_linked_to_the_original(
    client: AsyncClient,
) -> None:
    """Overwriting would destroy the only thing worth comparing against."""
    first = await run_scan(client)

    second = await _rerun(client, first)

    assert second != first
    summary = (await client.get(f"{API}/scans/{second}")).json()
    assert summary["rerun_of_id"] == first


async def test_a_rerun_targets_the_same_businesses(client: AsyncClient) -> None:
    first = await run_scan(client, "domain\nacme.com\nbeta.com\n")

    second = await _rerun(client, first)

    assert sorted(r["domain"] for r in await rows(client, second)) == ["acme.com", "beta.com"]


async def test_the_original_results_survive_a_rerun(client: AsyncClient) -> None:
    """History is the product here. A re-run must not rewrite the past."""
    set_profile("acme.com", NEGLECTED)
    first = await run_scan(client)
    before = (await rows(client, first))[0]["scores"]["security"]

    set_profile("acme.com", HEALTHY)
    second = await _rerun(client, first)

    assert (await rows(client, first))[0]["scores"]["security"] == before
    assert (await rows(client, second))[0]["scores"]["security"] > before


async def test_a_running_scan_cannot_be_rerun(client: AsyncClient) -> None:
    """Two scans of the same targets racing each other would produce a
    comparison against a moving baseline."""
    scan_id = await start_scan(client)

    response = await client.post(f"{API}/scans/{scan_id}/rerun")

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_a_scan_with_no_websites_cannot_be_rerun(client: AsyncClient) -> None:
    scan_id = await run_scan(client, "domain\n\n")

    response = await client.post(f"{API}/scans/{scan_id}/rerun")

    assert response.status_code == 409
    assert "no websites" in response.json()["detail"].lower()


async def test_rerunning_an_unknown_scan_returns_404(client: AsyncClient) -> None:
    assert (await client.post(f"{API}/scans/{uuid.uuid4()}/rerun")).status_code == 404


# ================================================================ comparing


async def test_an_unchanged_site_is_reported_as_unchanged(client: AsyncClient) -> None:
    first = await run_scan(client)
    second = await _rerun(client, first)

    comparison = await _compare(client, first, second)

    assert comparison["unchanged"] == 1
    assert comparison["changed"] == 0
    assert _for(comparison, "acme.com")["state"] == "unchanged"


async def test_a_site_that_was_fixed_shows_resolved_opportunities(
    client: AsyncClient,
) -> None:
    """The follow-up call: 'you sorted the certificate, but...'"""
    set_profile("acme.com", NEGLECTED)
    first = await run_scan(client)

    set_profile("acme.com", HEALTHY)
    second = await _rerun(client, first)

    entry = _for(await _compare(client, first, second), "acme.com")
    assert entry["state"] == "changed"
    assert entry["opportunities_resolved"]
    assert not entry["opportunities_gained"]
    assert entry["scores"]["security"]["change"] > 0


async def test_a_site_that_regressed_shows_gained_opportunities(
    client: AsyncClient,
) -> None:
    """The reason to call: something got worse since we last looked."""
    set_profile("acme.com", HEALTHY)
    first = await run_scan(client)

    set_profile("acme.com", NEGLECTED)
    second = await _rerun(client, first)

    entry = _for(await _compare(client, first, second), "acme.com")
    assert entry["state"] == "changed"
    assert entry["opportunities_gained"]
    assert entry["scores"]["security"]["change"] < 0


async def test_score_deltas_report_both_sides_not_just_the_difference(
    client: AsyncClient,
) -> None:
    """A UI showing '+18' without '54 -> 72' cannot be sanity-checked."""
    set_profile("acme.com", NEGLECTED)
    first = await run_scan(client)
    set_profile("acme.com", HEALTHY)
    second = await _rerun(client, first)

    delta = _for(await _compare(client, first, second), "acme.com")["scores"]["security"]

    assert delta["before"] is not None
    assert delta["after"] is not None
    assert delta["change"] == delta["after"] - delta["before"]


async def test_a_new_domain_is_reported_as_added(client: AsyncClient) -> None:
    first = await run_scan(client, "domain\nacme.com\n")
    second = await run_scan(client, "domain\nacme.com\nbeta.com\n")

    comparison = await _compare(client, first, second)

    assert comparison["added"] == 1
    assert _for(comparison, "beta.com")["state"] == "added"


async def test_a_dropped_domain_is_reported_as_removed(client: AsyncClient) -> None:
    first = await run_scan(client, "domain\nacme.com\nbeta.com\n")
    second = await run_scan(client, "domain\nacme.com\n")

    comparison = await _compare(client, first, second)

    assert comparison["removed"] == 1
    assert _for(comparison, "beta.com")["state"] == "removed"


async def test_the_totals_account_for_every_domain(client: AsyncClient) -> None:
    first = await run_scan(client, "domain\nacme.com\nbeta.com\n")
    second = await run_scan(client, "domain\nacme.com\ngamma.com\n")

    comparison = await _compare(client, first, second)

    counted = (
        comparison["added"]
        + comparison["removed"]
        + comparison["changed"]
        + comparison["unchanged"]
    )
    assert counted == comparison["total_compared"] == 3


async def test_comparing_a_scan_with_itself_reports_no_change(
    client: AsyncClient,
) -> None:
    """A degenerate case, but a diff that invents changes here would invent
    them anywhere."""
    scan_id = await run_scan(client, "domain\nacme.com\nbeta.com\n")

    comparison = await _compare(client, scan_id, scan_id)

    assert comparison["unchanged"] == 2
    assert comparison["changed"] == comparison["added"] == comparison["removed"] == 0


async def test_comparing_against_an_unknown_scan_returns_404(
    client: AsyncClient,
) -> None:
    scan_id = await run_scan(client)

    response = await client.get(f"{API}/scans/{scan_id}/compare/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
