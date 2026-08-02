"""Transaction boundaries.

Every write operation must have committed by the time it returns.

This is not a style preference. FastAPI runs a yield-dependency's teardown
*after* the response has been sent, so a service that leaves the commit to
the dependency hands the client a scan id for a row that is not durable yet.
The next request lands on a different pooled connection and gets a 404.
Against real PostgreSQL that happened in roughly one request in twelve.

`session.in_transaction()` is the assertion because it is exactly the
property that was wrong: an open transaction at return time means the caller
is holding an id for data nobody else can see.
"""

from __future__ import annotations

import uuid

import pytest

from leadkhojo.api import schemas
from leadkhojo.api.service import ScanService
from leadkhojo.db.repository import ScanRepository
from leadkhojo.jobs.queue import PostgresJobQueue

pytestmark = pytest.mark.asyncio


@pytest.fixture
def service(session, test_settings) -> ScanService:  # type: ignore[no-untyped-def]
    return ScanService(session, PostgresJobQueue(session), test_settings)


async def _terminal_scan_with_a_website(session) -> uuid.UUID:  # type: ignore[no-untyped-def]
    from leadkhojo.core.types import Domain, Url
    from leadkhojo.discovery.providers import DiscoveredBusiness

    repo = ScanRepository(session)
    scan = await repo.create_scan(keyword="k", location=None, provider="manual", limit=25)
    await repo.add_businesses(
        scan.id,
        [
            DiscoveredBusiness(
                name="Acme",
                website_url=Url("https://acme.com/"),
                domain=Domain("acme.com"),
            )
        ],
    )
    await repo.finish_scan(scan.id, status="completed")
    await session.commit()
    return scan.id


async def test_creating_a_scan_commits_before_returning(service, session) -> None:  # type: ignore[no-untyped-def]
    await service.create_scan(schemas.CreateScanRequest(urls=["acme.com"]))

    assert not session.in_transaction(), "create_scan returned with work uncommitted"


async def test_creating_from_csv_commits_before_returning(service, session) -> None:  # type: ignore[no-untyped-def]
    await service.create_scan_from_csv(
        schemas.CreateScanFromCsvRequest(csv_content="domain\nacme.com\n")
    )

    assert not session.in_transaction()


async def test_a_rerun_commits_before_returning(service, session) -> None:  # type: ignore[no-untyped-def]
    scan_id = await _terminal_scan_with_a_website(session)

    await service.rerun_scan(scan_id)

    assert not session.in_transaction()


async def test_cancelling_commits_before_returning(service, session) -> None:  # type: ignore[no-untyped-def]
    scan = await service.create_scan(schemas.CreateScanRequest(urls=["acme.com"]))

    await service.cancel_scan(scan.id)

    assert not session.in_transaction()


async def test_deleting_commits_before_returning(service, session) -> None:  # type: ignore[no-untyped-def]
    scan = await service.create_scan(schemas.CreateScanRequest(urls=["acme.com"]))

    await service.delete_scan(scan.id)

    assert not session.in_transaction()


async def test_a_created_scan_is_visible_to_a_separate_session(engine, test_settings) -> None:  # type: ignore[no-untyped-def]
    """The behaviour the commit exists for: another connection can see it.

    This is the read-your-write guarantee the API promises by returning an id
    with its 202.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async with factory() as writer:
        service = ScanService(writer, PostgresJobQueue(writer), test_settings)
        scan = await service.create_scan(schemas.CreateScanRequest(urls=["acme.com"]))

    async with factory() as reader:
        found = await ScanRepository(reader).get_scan(scan.id)

    assert found is not None, "a scan the API acknowledged is invisible to the next request"


async def test_a_failed_write_leaves_nothing_behind(service, session) -> None:  # type: ignore[no-untyped-def]
    """Committing eagerly must not mean committing partial work."""
    with pytest.raises(Exception):  # noqa: B017 - any failure will do
        await service.create_scan(schemas.CreateScanRequest())  # no urls, no keyword

    assert await ScanRepository(session).count_scans() == 0
