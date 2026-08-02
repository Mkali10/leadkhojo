"""Shared test fixtures.

The whole test strategy rests on one idea: because the crawler is the only
component that touches the network, every plugin test is offline, deterministic
and instant. These builders are how a test constructs a snapshot without one.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from leadkhojo.core.config import Settings
from leadkhojo.core.types import (
    Domain,
    PageType,
    SnapshotStatus,
    Url,
)
from leadkhojo.crawler.snapshot import (
    CookieInfo,
    DnsInfo,
    PageCapture,
    SiteSnapshot,
    Timings,
    TlsInfo,
)
from leadkhojo.db.base import Base

FIXTURES = Path(__file__).parent / "fixtures" / "snapshots"

# A fixed clock. Certificate maths must not change meaning in thirty days.
FIXED_NOW = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    return FIXED_NOW


def make_page(
    url: str = "https://acme.com/",
    *,
    status: int = 200,
    html: str = "<html><body>Hello</body></html>",
    headers: dict[str, str] | None = None,
    page_type: PageType = PageType.HOME,
    response_time_ms: int = 200,
    size: int = 1024,
) -> PageCapture:
    return PageCapture(
        url=Url(url),
        final_url=Url(url),
        status=status,
        headers={k.lower(): v for k, v in (headers or {}).items()},
        html=html,
        text=html,
        content_hash="sha256:test",
        bytes=size,
        response_time_ms=response_time_ms,
        page_type=page_type,
    )


def make_snapshot(
    *,
    domain: str = "acme.com",
    url: str = "https://acme.com/",
    pages: tuple[PageCapture, ...] | None = None,
    tls: TlsInfo | None = None,
    dns: DnsInfo | None = None,
    cookies: tuple[CookieInfo, ...] = (),
    status: SnapshotStatus = SnapshotStatus.COMPLETE,
    timings: Timings | None = None,
) -> SiteSnapshot:
    return SiteSnapshot(
        domain=Domain(domain),
        requested_url=Url(url),
        final_url=Url(url),
        status=status,
        captured_at=FIXED_NOW,
        http_status=200,
        pages=pages if pages is not None else (make_page(url),),
        tls=tls,
        dns=dns,
        cookies=cookies,
        timings=timings or Timings(ttfb_ms=200, total_ms=800),
    )


def make_tls(
    *,
    days_until_expiry: int = 200,
    protocol: str = "TLSv1.3",
    self_signed: bool = False,
    hostname_matches: bool = True,
) -> TlsInfo:
    from datetime import timedelta

    return TlsInfo(
        protocol=protocol,
        cipher="TLS_AES_256_GCM_SHA384",
        issuer="Let's Encrypt R3",
        subject="acme.com",
        sans=("acme.com", "www.acme.com"),
        not_before=FIXED_NOW - timedelta(days=30),
        not_after=FIXED_NOW + timedelta(days=days_until_expiry),
        is_self_signed=self_signed,
        chain_complete=True,
        hostname_matches=hostname_matches,
    )


def make_dns(
    *,
    spf: str | None = "v=spf1 include:_spf.google.com ~all",
    dmarc: str | None = "v=DMARC1; p=reject; rua=mailto:d@acme.com",
    mx: tuple[str, ...] = ("10 mail.acme.com",),
    dnssec: bool = True,
) -> DnsInfo:
    return DnsInfo(
        a=("93.184.216.34",),
        mx=mx,
        ns=("ns1.acme.com",),
        txt=(spf,) if spf else (),
        dmarc=dmarc,
        dnssec=dnssec,
        resolved_ip="93.184.216.34",
    )


@pytest.fixture
def load_fixture():  # type: ignore[no-untyped-def]
    def _load(name: str) -> SiteSnapshot:
        path = FIXTURES / f"{name}.json"
        if not path.is_file():
            pytest.skip(f"Fixture not captured yet: {name}")
        return SiteSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))

    return _load


@pytest.fixture(scope="session")
def rules_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "rules"


# ---------------------------------------------------------------- database
# Tests run against SQLite by default so the suite needs no service. The
# schema targets PostgreSQL; JSON/UUID columns use dialect variants so the
# models are identical either way.
#
# SQLite is not a substitute, and pretending otherwise cost real bugs:
#   * it stores NUL bytes that PostgreSQL rejects outright (see the NUL
#     regression tests in test_persistence.py)
#   * it has no row locking, so FOR UPDATE SKIP LOCKED is never exercised
#   * one shared connection hides read-your-write races across a pool
#
# So point the suite at a real PostgreSQL and run it again before shipping:
#
#     createdb leadkhojo_test
#     LK_TEST_DATABASE_URL=postgresql+asyncpg://user:pw@localhost/leadkhojo_test \
#         pytest tests/
#
# The schema is dropped and recreated per test, so use a throwaway database.

TEST_DATABASE_URL = os.environ.get("LK_TEST_DATABASE_URL")


@pytest_asyncio.fixture
async def engine():  # type: ignore[no-untyped-def]
    """A fresh database per test. No cross-test leakage either way."""
    if TEST_DATABASE_URL:
        test_engine = create_async_engine(TEST_DATABASE_URL, future=True, poolclass=NullPool)
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        try:
            yield test_engine
        finally:
            await test_engine.dispose()
        return

    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        # SQLite ignores foreign keys unless asked, which would silently hide
        # every cascade-delete bug we care about.
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    try:
        yield test_engine
    finally:
        await test_engine.dispose()


@pytest_asyncio.fixture
async def session(engine):  # type: ignore[no-untyped-def]
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with factory() as db_session:
        if not TEST_DATABASE_URL:
            # PRAGMA is per-connection, so re-assert it on this one.
            await db_session.execute(text("PRAGMA foreign_keys=ON"))
        yield db_session


@pytest.fixture
def test_settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="sqlite+aiosqlite:///:memory:",
        rules_dir=Path(__file__).resolve().parents[2] / "rules",
        export_dir=tmp_path / "exports",
        worker_count=1,
    )
