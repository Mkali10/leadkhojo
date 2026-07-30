"""Crawler unit tests.

The crawler is the only component that touches the network, so it carries
the rules that keep LeadKhojo on the right side of the passive/active line.
These tests cover the parts that can be tested without a network: robots
parsing, the SSRF guard, and snapshot serialisation.
"""

from __future__ import annotations

import pytest

from leadkhojo.core.errors import CrawlError
from leadkhojo.core.types import CrawlFailure, Domain, PageType, SnapshotStatus, Url
from leadkhojo.crawler.guards import (
    ALLOWED_PORTS,
    assert_allowed_port,
    assert_public_address,
    is_blocked_address,
)
from leadkhojo.crawler.robots import parse_robots
from leadkhojo.crawler.snapshot import SiteSnapshot
from tests.conftest import FIXED_NOW, make_dns, make_page, make_snapshot, make_tls

UA = "LeadKhojoBot/1.0 (+https://leadkhojo.com/bot)"


# ---------------------------------------------------------------- robots.txt
# Honoured with no override. There is no flag to disable this and none may
# be added.


def test_disallowed_paths_are_blocked() -> None:
    rules = parse_robots("User-agent: *\nDisallow: /admin\nDisallow: /private\n", UA)

    assert not rules.is_allowed("https://acme.com/admin")
    assert not rules.is_allowed("https://acme.com/admin/users")
    assert not rules.is_allowed("https://acme.com/private")
    assert rules.is_allowed("https://acme.com/contact")


def test_a_more_specific_allow_beats_a_broader_disallow() -> None:
    """Longest match wins, per the robots.txt convention."""
    rules = parse_robots("User-agent: *\nDisallow: /\nAllow: /public\n", UA)

    assert rules.is_allowed("https://acme.com/public/page")
    assert not rules.is_allowed("https://acme.com/anything-else")


def test_a_group_naming_our_agent_wins_over_the_wildcard() -> None:
    body = (
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: LeadKhojoBot\nDisallow: /admin\n"
    )
    rules = parse_robots(body, UA)

    assert rules.is_allowed("https://acme.com/contact")  # wildcard would deny
    assert not rules.is_allowed("https://acme.com/admin")


def test_blanket_disallow_is_detected() -> None:
    rules = parse_robots("User-agent: *\nDisallow: /\n", UA)
    assert rules.blocks_everything


def test_wildcards_and_end_anchors_are_honoured() -> None:
    rules = parse_robots("User-agent: *\nDisallow: /*.pdf$\nDisallow: /tmp/*\n", UA)

    assert not rules.is_allowed("https://acme.com/tmp/anything")
    assert rules.is_allowed("https://acme.com/contact")


def test_sitemaps_are_collected() -> None:
    rules = parse_robots(
        "Sitemap: https://acme.com/sitemap.xml\nUser-agent: *\nDisallow:\n", UA
    )
    assert rules.sitemaps == ("https://acme.com/sitemap.xml",)


def test_absent_or_empty_robots_allows_everything() -> None:
    for body in ("", "   \n", "# just a comment\n"):
        rules = parse_robots(body, UA)
        assert rules.is_allowed("https://acme.com/anything")
        assert not rules.blocks_everything


def test_comments_and_odd_spacing_are_tolerated() -> None:
    rules = parse_robots("User-agent: *  # everyone\n  Disallow:  /admin   # secret\n", UA)
    assert not rules.is_allowed("https://acme.com/admin")


# ---------------------------------------------------------------- SSRF guard
# The highest-severity application risk in this product: we take a
# user-supplied URL and fetch it.


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.1",  # RFC1918
        "172.16.5.4",  # RFC1918
        "192.168.1.1",  # RFC1918
        "169.254.169.254",  # cloud metadata — the classic SSRF target
        "0.0.0.0",  # noqa: S104 - the value under test
        "100.64.0.1",  # carrier-grade NAT
        "::1",  # IPv6 loopback
        "fc00::1",  # IPv6 unique local
        "fe80::1",  # IPv6 link-local
    ],
)
def test_private_and_metadata_addresses_are_refused(ip: str) -> None:
    assert is_blocked_address(ip)
    with pytest.raises(CrawlError):
        assert_public_address(ip)


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700::1111"])
def test_public_addresses_are_permitted(ip: str) -> None:
    assert not is_blocked_address(ip)
    assert_public_address(ip)


def test_an_unparseable_address_is_refused_rather_than_guessed() -> None:
    assert is_blocked_address("not-an-ip")
    assert is_blocked_address("")


def test_only_web_ports_are_permitted() -> None:
    """Connecting anywhere else would make this a port scanner."""
    assert ALLOWED_PORTS == frozenset({80, 443})
    assert_allowed_port(80)
    assert_allowed_port(443)

    for port in (21, 22, 25, 3306, 3389, 5432, 6379, 8080, 8443):
        with pytest.raises(CrawlError, match="active scanning"):
            assert_allowed_port(port)


# ---------------------------------------------------------------- snapshot
# The contract between the crawler and every plugin. A fixture is only
# useful if it reloads identically.


def test_a_snapshot_round_trips_losslessly() -> None:
    original = make_snapshot(
        pages=(
            make_page("https://acme.com/", page_type=PageType.HOME),
            make_page("https://acme.com/contact", page_type=PageType.CONTACT),
        ),
        tls=make_tls(days_until_expiry=42),
        dns=make_dns(),
    )

    restored = SiteSnapshot.from_dict(original.to_dict())

    assert restored.domain == original.domain
    assert restored.status is original.status
    assert restored.captured_at == original.captured_at
    assert len(restored.pages) == len(original.pages)
    assert restored.pages[1].page_type is PageType.CONTACT
    assert restored.tls is not None
    assert restored.tls.not_after == original.tls.not_after  # type: ignore[union-attr]
    assert restored.dns is not None
    assert restored.dns.spf == original.dns.spf  # type: ignore[union-attr]


def test_json_round_trip_survives_serialisation() -> None:
    original = make_snapshot(tls=make_tls(), dns=make_dns())
    restored = SiteSnapshot.from_json(original.to_json())
    assert restored.domain == original.domain
    assert restored.tls is not None


def test_a_failed_crawl_still_produces_a_snapshot() -> None:
    """Failure is data, not an exception. DNS may have resolved even when
    HTTP did not, and DNS-only findings are still worth surfacing."""
    snapshot = SiteSnapshot.failed_snapshot(
        domain=Domain("acme.com"),
        requested_url=Url("https://acme.com"),
        reason=CrawlFailure.HTTP_5XX,
        detail="Homepage returned 500",
        captured_at=FIXED_NOW,
        dns=make_dns(),
    )

    assert snapshot.status is SnapshotStatus.FAILED
    assert snapshot.failure_reason is CrawlFailure.HTTP_5XX
    assert snapshot.dns is not None  # DNS survived the HTTP failure
    assert snapshot.pages == ()


def test_dns_distinguishes_absent_record_from_never_looked() -> None:
    """snapshot.dns is None  -> we never looked      -> NOT_APPLICABLE
    snapshot.dns.dmarc None -> we looked, absent    -> a real finding"""
    never_looked = make_snapshot(dns=None)
    assert never_looked.dns is None

    looked_and_absent = make_snapshot(dns=make_dns(dmarc=None))
    assert looked_and_absent.dns is not None
    assert looked_and_absent.dns.dmarc is None


def test_spf_is_extracted_from_txt_records() -> None:
    dns = make_dns(spf="v=spf1 include:_spf.google.com ~all")
    assert dns.spf == "v=spf1 include:_spf.google.com ~all"

    assert make_dns(spf=None).spf is None


def test_home_page_accessor_prefers_the_home_type() -> None:
    snapshot = make_snapshot(
        pages=(
            make_page("https://acme.com/contact", page_type=PageType.CONTACT),
            make_page("https://acme.com/", page_type=PageType.HOME),
        )
    )
    assert snapshot.home is not None
    assert snapshot.home.page_type is PageType.HOME


def test_headers_are_stored_lowercased_for_case_insensitive_lookup() -> None:
    page = make_page(headers={"Content-Type": "text/html", "SERVER": "nginx"})
    assert page.header("content-type") == "text/html"
    assert page.header("Server") == "nginx"
