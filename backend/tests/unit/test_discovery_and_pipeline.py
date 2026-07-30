"""Discovery and pipeline orchestration tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from leadkhojo.core.config import Settings
from leadkhojo.core.errors import InvalidCsvError
from leadkhojo.core.types import Domain, Url
from leadkhojo.crawler.snapshot import SiteSnapshot
from leadkhojo.discovery.providers import CsvImportProvider, DiscoveredBusiness
from leadkhojo.pipeline.runner import PipelineRunner
from leadkhojo.plugins.engine import PluginEngine
from tests.conftest import make_snapshot

# ---------------------------------------------------------------- CSV import


def _parse(content: str, limit: int = 500):  # type: ignore[no-untyped-def]
    return CsvImportProvider(content).parse(limit=limit)


def test_a_simple_domain_list_is_imported() -> None:
    result = _parse("name,domain\nAcme,acme.com\nBeta,beta.co.uk\n")

    assert len(result.businesses) == 2
    assert result.businesses[0].name == "Acme"
    assert result.businesses[1].domain == "beta.co.uk"


def test_column_names_are_detected_flexibly() -> None:
    for header in ("domain", "website", "url", "Website URL", "Company Website"):
        result = _parse(f"{header}\nacme.com\n")
        assert len(result.businesses) == 1, f"{header!r} should be detected"


def test_a_missing_domain_column_is_a_clear_error() -> None:
    with pytest.raises(InvalidCsvError, match="No domain or website column"):
        _parse("company,city\nAcme,Austin\n")


def test_invalid_rows_are_reported_individually_with_row_numbers() -> None:
    """The user must be told which rows to fix, not just that something is
    wrong."""
    result = _parse("domain\nacme.com\n\nn/a\nbeta.com\n")

    assert len(result.businesses) == 2
    assert {e.row for e in result.errors}
    assert all(e.reason for e in result.errors)


def test_duplicate_domains_are_deduplicated_silently() -> None:
    """A repeat is not a user error worth reporting — it is just a repeat."""
    result = _parse("domain\nacme.com\nwww.acme.com\nhttps://acme.com/contact\n")

    assert len(result.businesses) == 1
    assert result.businesses[0].domain == "acme.com"
    assert not result.errors


def test_urls_are_normalised_to_a_fetchable_form() -> None:
    result = _parse("domain\nacme.com\n")
    assert result.businesses[0].website_url == "https://acme.com"


def test_the_limit_is_honoured() -> None:
    rows = "\n".join(f"site{i}.com" for i in range(50))
    assert len(_parse(f"domain\n{rows}\n", limit=10).businesses) == 10


def test_semicolon_delimited_files_are_handled() -> None:
    result = _parse("name;domain\nAcme;acme.com\n")
    assert len(result.businesses) == 1


def test_an_oversized_upload_is_rejected_before_parsing() -> None:
    with pytest.raises(InvalidCsvError, match="limit"):
        CsvImportProvider(b"x" * (6 * 1024 * 1024))


def test_a_header_only_file_yields_nothing_without_erroring() -> None:
    assert _parse("domain\n").businesses == ()


# ---------------------------------------------------------------- pipeline


class _FakeCrawler:
    """Stands in for the network. The pipeline must never require one."""

    def __init__(self, snapshot: SiteSnapshot | None = None, explode: bool = False) -> None:
        self._snapshot = snapshot
        self._explode = explode
        self.calls: list[str] = []

    async def crawl(self, url: str, *, now: datetime | None = None) -> SiteSnapshot:
        self.calls.append(url)
        if self._explode:
            raise RuntimeError("network on fire")
        return self._snapshot or make_snapshot()


def _business(name: str = "Acme", domain: str = "acme.com") -> DiscoveredBusiness:
    return DiscoveredBusiness(
        name=name, website_url=Url(f"https://{domain}"), domain=Domain(domain)
    )


@pytest.fixture
def runner_factory():  # type: ignore[no-untyped-def]
    def _make(crawler: _FakeCrawler) -> PipelineRunner:
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        return PipelineRunner(settings, PluginEngine([]), crawler)  # type: ignore[arg-type]

    return _make


async def test_a_business_without_a_website_is_skipped_not_crawled(runner_factory) -> None:  # type: ignore[no-untyped-def]
    crawler = _FakeCrawler()
    runner = runner_factory(crawler)

    result = await runner.analyze_one(
        DiscoveredBusiness(name="No Site", website_url=None, domain=None)
    )

    assert not result.ok
    assert result.error is not None
    assert crawler.calls == []


async def test_a_crawler_exception_fails_only_that_business(runner_factory) -> None:  # type: ignore[no-untyped-def]
    """One site must never break a scan."""
    runner = runner_factory(_FakeCrawler(explode=True))

    result = await runner.analyze_one(_business())

    assert not result.ok
    assert "RuntimeError" in (result.error or "")


async def test_every_business_gets_a_result_even_when_some_fail(runner_factory) -> None:  # type: ignore[no-untyped-def]
    runner = runner_factory(_FakeCrawler(explode=True))

    scan = await runner.run((_business("A", "a.com"), _business("B", "b.com")))

    assert len(scan.results) == 2
    assert len(scan.failed) == 2
    assert scan.succeeded == ()


async def test_progress_is_reported_for_each_business(runner_factory) -> None:  # type: ignore[no-untyped-def]
    """The UI must be able to name the business currently being analysed
    rather than showing an anonymous spinner."""
    seen: list[tuple[int, int, str]] = []
    runner = runner_factory(_FakeCrawler())

    await runner.run(
        (_business("A", "a.com"), _business("B", "b.com")),
        on_progress=lambda done, total, name: seen.append((done, total, name)),
    )

    assert len(seen) == 2
    assert seen[-1][0] == 2
    assert all(entry[1] == 2 for entry in seen)


async def test_results_can_be_ranked_by_any_score(runner_factory) -> None:  # type: ignore[no-untyped-def]
    runner = runner_factory(_FakeCrawler())
    scan = await runner.run((_business("A", "a.com"),))

    assert scan.ranked_by("opportunity") == scan.succeeded
    assert scan.duration_seconds >= 0
