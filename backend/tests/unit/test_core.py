"""Core module unit tests.

Pure functions, no I/O. These are the primitives everything else is built on,
so a bug here surfaces everywhere at once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from leadkhojo.core.findings import Finding, sort_findings
from leadkhojo.core.types import CheckId, FindingStatus, PluginId, Severity
from leadkhojo.core.utils.clock import days_between, ensure_utc, iso
from leadkhojo.core.utils.domains import (
    canonical_domain,
    join_url,
    normalize_url,
    same_registrable_domain,
    url_path,
)
from leadkhojo.core.utils.versions import Version, is_outdated, major_versions_behind, parse

# ---------------------------------------------------------------- domains
# Deduplication depends entirely on this being right.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("acme.com", "acme.com"),
        ("www.acme.com", "acme.com"),
        ("https://acme.com", "acme.com"),
        ("https://www.acme.com/contact?x=1#frag", "acme.com"),
        ("HTTPS://ACME.COM", "acme.com"),
        ("acme.com.", "acme.com"),
        ("shop.eu.acme.com", "acme.com"),
        # Multi-part public suffixes are the case a naive dot-split gets wrong.
        ("www.acme.co.uk", "acme.co.uk"),
        ("acme.com.au", "acme.com.au"),
    ],
)
def test_canonical_domain_collapses_variants(raw: str, expected: str) -> None:
    assert canonical_domain(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "not a domain", "http://", "just-text"])
def test_canonical_domain_rejects_rubbish(raw: str) -> None:
    assert canonical_domain(raw) is None


def test_normalize_url_defaults_to_https_and_drops_fragments() -> None:
    assert normalize_url("acme.com") == "https://acme.com"
    assert normalize_url("http://acme.com/x#frag") == "http://acme.com/x"
    assert normalize_url("ftp://acme.com") is None
    assert normalize_url("") is None


def test_same_registrable_domain_ignores_subdomains_and_scheme() -> None:
    assert same_registrable_domain("https://www.acme.com/a", "http://shop.acme.com/b")
    assert not same_registrable_domain("https://acme.com", "https://other.com")


def test_join_url_resolves_relative_and_skips_non_http_schemes() -> None:
    assert join_url("https://acme.com/a/b", "../contact") == "https://acme.com/contact"
    assert join_url("https://acme.com/", "/about") == "https://acme.com/about"
    for skipped in ("mailto:x@y.com", "tel:+1234", "#top", "javascript:void(0)", ""):
        assert join_url("https://acme.com/", skipped) is None


def test_url_path_always_starts_with_slash() -> None:
    assert url_path("https://acme.com") == "/"
    assert url_path("https://acme.com/contact") == "/contact"


# ---------------------------------------------------------------- versions
# A wrong comparison here flags a current site as outdated, which puts a false
# claim in front of a prospect.


@pytest.mark.parametrize(
    ("lower", "higher"),
    [
        ("1.9", "1.10"),  # the classic naive-tuple failure
        ("5.4.2", "5.5"),
        ("1.0", "2.0"),
        ("5.4.2-beta", "5.4.2"),  # a prerelease is older than its release
        ("2.0.0", "2.0.1"),
    ],
)
def test_version_ordering(lower: str, higher: str) -> None:
    assert Version(lower) < Version(higher)


def test_version_equality_pads_missing_components() -> None:
    assert Version("5.4") == Version("5.4.0")
    assert Version("v2.0") == Version("2.0")


@pytest.mark.parametrize("raw", ["", "unknown", "latest", "abc"])
def test_unparseable_versions_are_invalid_not_crashes(raw: str) -> None:
    assert parse(raw) is None
    assert not Version(raw).is_valid


def test_is_outdated_returns_none_when_it_cannot_tell() -> None:
    """None is a real answer, and the specificity gate depends on it.

    An unknown version must never produce "your CMS might be old".
    """
    assert is_outdated("5.4", "6.7") is True
    assert is_outdated("6.7", "6.7") is False
    assert is_outdated(None, "6.7") is None
    assert is_outdated("5.4", None) is None
    assert is_outdated("garbage", "6.7") is None


def test_major_versions_behind() -> None:
    assert major_versions_behind("4.2", "6.7") == 2
    assert major_versions_behind("6.7", "6.7") == 0
    assert major_versions_behind("7.0", "6.7") == 0  # never negative
    assert major_versions_behind(None, "6.7") is None


# ---------------------------------------------------------------- clock


def test_ensure_utc_makes_naive_datetimes_comparable() -> None:
    """Certificate parsing hands back datetimes that are UTC in fact but not
    in type. Comparing one to an aware datetime raises TypeError."""
    naive = datetime(2026, 7, 30, 12, 0, 0)  # noqa: DTZ001 - the case under test
    assert ensure_utc(naive).tzinfo is UTC
    aware = datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)
    assert ensure_utc(naive) == aware  # no exception


def test_days_between_is_signed() -> None:
    start = datetime(2026, 7, 30, tzinfo=UTC)
    assert days_between(start, start + timedelta(days=9)) == 9
    assert days_between(start, start - timedelta(days=5)) == -5


def test_iso_uses_a_z_suffix() -> None:
    assert iso(datetime(2026, 7, 30, 12, 0, 0, tzinfo=UTC)) == "2026-07-30T12:00:00Z"


# ---------------------------------------------------------------- findings


def _finding(status: FindingStatus, severity: Severity, check_id: str = "X-01") -> Finding:
    return Finding(
        check_id=CheckId(check_id),
        plugin_id=PluginId("test"),
        category="test",
        status=status,
        severity=severity,
        title="t",
        description="d",
        evidence={"seen": True},
    )


def test_a_problem_finding_without_evidence_is_rejected() -> None:
    """Evidence is what the user pastes into an email. A finding without it
    is not shippable, so the type refuses to construct one."""
    with pytest.raises(ValueError, match="evidence"):
        Finding(
            check_id=CheckId("X-01"),
            plugin_id=PluginId("test"),
            category="test",
            status=FindingStatus.FAIL,
            severity=Severity.HIGH,
            title="t",
            description="d",
            evidence={},
        )


def test_passing_findings_may_be_evidence_light() -> None:
    finding = Finding.passed("X-01", plugin_id="test", category="test", title="fine")
    assert finding.status is FindingStatus.PASS
    assert not finding.is_problem


def test_not_applicable_records_why_we_could_not_check() -> None:
    """ "We could not check" is not "you failed"."""
    finding = Finding.not_applicable(
        "TLS-04", plugin_id="ssl", category="tls", reason="No TLS connection"
    )
    assert finding.status is FindingStatus.NOT_APPLICABLE
    assert not finding.is_problem
    assert finding.evidence["reason"] == "No TLS connection"


def test_only_fail_and_warn_count_as_problems() -> None:
    assert FindingStatus.FAIL.is_problem
    assert FindingStatus.WARN.is_problem
    assert not FindingStatus.PASS.is_problem
    assert not FindingStatus.INFO.is_problem
    assert not FindingStatus.NOT_APPLICABLE.is_problem


def test_findings_sort_problems_first_worst_first_then_stably() -> None:
    findings = (
        _finding(FindingStatus.PASS, Severity.INFO, "A-01"),
        _finding(FindingStatus.FAIL, Severity.MEDIUM, "C-01"),
        _finding(FindingStatus.FAIL, Severity.CRITICAL, "B-01"),
        _finding(FindingStatus.WARN, Severity.LOW, "D-01"),
    )
    ordered = [f.check_id for f in sort_findings(findings)]
    assert ordered == ["B-01", "C-01", "D-01", "A-01"]


def test_severity_ranks_are_ordered_worst_first() -> None:
    ranks = [s.rank for s in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW)]
    assert ranks == sorted(ranks)
    assert Severity.CRITICAL.weight > Severity.LOW.weight
