"""Fixtures for tests that go through the HTTP surface.

One stub, one seam: the crawler. Everything else — the app, the database,
the job queue, the plugin engine, the scoring — is the real thing, because
an integration test that mocks the interesting parts only proves the mocks
agree with each other.

The stub is driven by SITE_PROFILES, a per-test registry of what each domain
is currently serving. Mutating it between two scans of the same target is
how the comparison tests simulate a site that changed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

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
from tests.conftest import FIXED_NOW, make_dns, make_page, make_tls

API = "/api/v1"


@dataclass(frozen=True, slots=True)
class SiteProfile:
    """What a stubbed website is serving right now."""

    email: str | None = "hello@{domain}"
    cert_days: int = 9  # close to expiry, so the run has something to say
    dmarc: str | None = None  # absent, so email security fails


NEGLECTED = SiteProfile()
HEALTHY = SiteProfile(cert_days=400, dmarc="v=DMARC1; p=reject; rua=mailto:d@acme.com")
NO_CONTACT = SiteProfile(email=None)

# domain -> profile. Reset before every test by the `sites` fixture.
SITE_PROFILES: dict[str, SiteProfile] = {}


def set_profile(domain: str, profile: SiteProfile) -> None:
    SITE_PROFILES[domain] = profile


def _profile_for(domain: str) -> SiteProfile:
    if domain in SITE_PROFILES:
        return SITE_PROFILES[domain]
    # A domain named for what it should do keeps tests readable without
    # a setup line each time.
    if domain.startswith("nocontact"):
        return NO_CONTACT
    if domain.startswith("healthy"):
        return HEALTHY
    return NEGLECTED


def _html(profile: SiteProfile, domain: str) -> str:
    if profile.email is None:
        return "<html><body><h1>Quiet Co</h1><p>No way to reach us.</p></body></html>"
    address = profile.email.format(domain=domain)
    return f'<html><body><h1>Acme Dental</h1><a href="mailto:{address}">Email us</a></body></html>'


class StubCrawler:
    """Stands in for CrawlerService. Same shape, no sockets."""

    def __init__(self, settings: object) -> None:
        self._settings = settings

    async def crawl(self, url: str, *, now: object = None) -> SiteSnapshot:
        domain = url.removeprefix("https://").removeprefix("http://").strip("/")
        profile = _profile_for(domain)
        return SiteSnapshot(
            domain=Domain(domain),
            requested_url=Url(url),
            final_url=Url(url),
            status=SnapshotStatus.COMPLETE,
            captured_at=FIXED_NOW,
            http_status=200,
            pages=(make_page(url, html=_html(profile, domain)),),
            tls=make_tls(days_until_expiry=profile.cert_days),
            dns=make_dns(dmarc=profile.dmarc),
        )


@pytest.fixture
def sites() -> Iterator[dict[str, SiteProfile]]:
    """A clean site registry per test. Global mutable state leaks otherwise."""
    SITE_PROFILES.clear()
    yield SITE_PROFILES
    SITE_PROFILES.clear()


@pytest_asyncio.fixture
async def client(
    engine, test_settings, rules_dir, sites, monkeypatch
) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    from leadkhojo.jobs import handlers

    monkeypatch.setattr(handlers, "CrawlerService", StubCrawler)

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


# ---------------------------------------------------------------- helpers
# Workers are driven explicitly rather than left polling in the background,
# so assertions run against a settled state instead of racing an interval.


async def drain(budget_seconds: float = 30.0) -> int:
    pool = deps.get_worker_pool()
    assert pool is not None
    return await pool.drain(timeout=budget_seconds)


async def start_scan(client: AsyncClient, csv: str = "domain\nacme.com\n") -> str:
    files = {"file": ("domains.csv", csv.encode(), "text/csv")}
    response = await client.post(f"{API}/scans/csv", files=files)
    assert response.status_code == 202, response.text
    return str(response.json()["id"])


async def run_scan(client: AsyncClient, csv: str = "domain\nacme.com\n") -> str:
    scan_id = await start_scan(client, csv)
    await drain()
    return scan_id


async def rows(client: AsyncClient, scan_id: str, query: str = "") -> list[dict]:
    response = await client.get(f"{API}/scans/{scan_id}/businesses{query}")
    assert response.status_code == 200, response.text
    return list(response.json()["data"])


__all__ = [
    "API",
    "HEALTHY",
    "NEGLECTED",
    "NO_CONTACT",
    "SITE_PROFILES",
    "SiteProfile",
    "StubCrawler",
    "drain",
    "rows",
    "run_scan",
    "set_profile",
    "start_scan",
]
