"""Security analyzer tests — SSL, DNS, headers, cookies and performance.

Every check is tested three ways, because the third is the one people skip
and the one that produces false accusations:

    fires correctly   — a real problem is reported
    stays silent      — a healthy site is not accused
    not applicable    — we could not evaluate, and say so
"""

from __future__ import annotations

from datetime import datetime

import pytest

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import FindingStatus, Severity
from leadkhojo.crawler.snapshot import CookieInfo, Timings
from leadkhojo.plugins.base import PluginContext
from leadkhojo.plugins.builtin.dns_plugin import DnsPlugin
from leadkhojo.plugins.builtin.headers_plugin import HeadersPlugin
from leadkhojo.plugins.builtin.performance_plugin import PerformancePlugin
from leadkhojo.plugins.builtin.ssl_plugin import SslPlugin
from tests.conftest import make_dns, make_page, make_snapshot, make_tls


def find(findings: tuple[Finding, ...], check_id: str) -> Finding:
    for f in findings:
        if f.check_id == check_id:
            return f
    raise AssertionError(f"{check_id} not in {[f.check_id for f in findings]}")


# ================================================================ SSL / TLS


@pytest.mark.parametrize(
    ("days", "expected"),
    [(3, Severity.CRITICAL), (7, Severity.CRITICAL), (9, Severity.HIGH), (25, Severity.HIGH)],
)
def test_expiry_severity_escalates_as_the_deadline_nears(
    days: int, expected: Severity, now: datetime
) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(tls=make_tls(days_until_expiry=days)), now=now
    )
    finding = find(SslPlugin().run(ctx).findings, "TLS-04")

    assert finding.status is FindingStatus.FAIL
    assert finding.severity is expected
    assert finding.evidence["days_remaining"] == days


def test_an_expired_certificate_is_critical_with_the_exact_date(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(tls=make_tls(days_until_expiry=-5)), now=now
    )
    finding = find(SslPlugin().run(ctx).findings, "TLS-03")

    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.CRITICAL
    assert finding.evidence["days_expired"] == 5
    assert "not_after" in finding.evidence  # the date is what makes it verifiable
    assert finding.remediation


def test_a_healthy_certificate_passes(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(tls=make_tls(days_until_expiry=200)), now=now
    )
    findings = SslPlugin().run(ctx).findings

    assert find(findings, "TLS-03").status is FindingStatus.PASS
    assert find(findings, "TLS-04").status is FindingStatus.PASS


def test_plain_http_is_critical_and_suppresses_certificate_checks(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(url="http://acme.com/", tls=None), now=now
    )
    findings = SslPlugin().run(ctx).findings

    assert find(findings, "TLS-01").severity is Severity.CRITICAL
    # Without a certificate, every downstream check is unevaluable — not failed.
    for check in ("TLS-03", "TLS-04", "TLS-05", "TLS-06"):
        assert find(findings, check).status is FindingStatus.NOT_APPLICABLE


def test_a_hostname_mismatch_is_critical(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(tls=make_tls(hostname_matches=False)), now=now
    )
    assert find(SslPlugin().run(ctx).findings, "TLS-05").severity is Severity.CRITICAL


def test_a_self_signed_certificate_is_reported(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(tls=make_tls(self_signed=True)), now=now)
    assert find(SslPlugin().run(ctx).findings, "TLS-08").status is FindingStatus.FAIL


def test_an_obsolete_tls_version_is_reported(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(tls=make_tls(protocol="TLSv1.0")), now=now
    )
    finding = find(SslPlugin().run(ctx).findings, "TLS-06")
    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.HIGH


def test_missing_tls_details_are_not_applicable_not_failures(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(url="https://acme.com/", tls=None), now=now
    )
    assert find(SslPlugin().run(ctx).findings, "TLS-03").status is FindingStatus.NOT_APPLICABLE


# ================================================================ DNS


def test_missing_dmarc_reports_the_query_and_the_answer(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(dns=make_dns(dmarc=None)), now=now)
    finding = find(DnsPlugin().run(ctx).findings, "DNS-03")

    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.HIGH
    assert finding.evidence["query"] == "_dmarc.acme.com TXT"
    assert finding.evidence["result"] == "NXDOMAIN"


def test_dmarc_presence_and_enforcement_are_separate_findings(now: datetime) -> None:
    """Having DMARC and enforcing it are different products to sell."""
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(dns=make_dns(dmarc="v=DMARC1; p=none; rua=mailto:x@acme.com")),
        now=now,
    )
    findings = DnsPlugin().run(ctx).findings

    assert find(findings, "DNS-03").status is FindingStatus.PASS
    policy = find(findings, "DNS-04")
    assert policy.status is FindingStatus.FAIL
    assert policy.evidence["policy"] == "none"


@pytest.mark.parametrize("policy", ["quarantine", "reject"])
def test_an_enforcing_dmarc_policy_passes(policy: str, now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(dns=make_dns(dmarc=f"v=DMARC1; p={policy}")), now=now
    )
    assert find(DnsPlugin().run(ctx).findings, "DNS-04").status is FindingStatus.PASS


def test_missing_spf_is_high_severity(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(dns=make_dns(spf=None)), now=now)
    finding = find(DnsPlugin().run(ctx).findings, "DNS-01")

    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.HIGH


@pytest.mark.parametrize(
    ("record", "status"),
    [
        ("v=spf1 +all", FindingStatus.FAIL),  # authorises the entire internet
        ("v=spf1 ?all", FindingStatus.WARN),  # neutral: no protection at all
        ("v=spf1 include:_spf.google.com", FindingStatus.WARN),  # no all mechanism
        ("v=spf1 ~all", FindingStatus.PASS),
        ("v=spf1 -all", FindingStatus.PASS),
    ],
)
def test_spf_strictness_is_graded(record: str, status: FindingStatus, now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(dns=make_dns(spf=record)), now=now)
    assert find(DnsPlugin().run(ctx).findings, "DNS-02").status is status


def test_no_dns_at_all_is_not_applicable_across_the_board(now: datetime) -> None:
    """'We never looked' must not be reported as 'you have no SPF'."""
    ctx = PluginContext.for_testing(snapshot=make_snapshot(dns=None), now=now)
    findings = DnsPlugin().run(ctx).findings

    for check in ("DNS-01", "DNS-02", "DNS-03", "DNS-04", "DNS-05", "DNS-06", "DNS-07"):
        assert find(findings, check).status is FindingStatus.NOT_APPLICABLE


def test_a_missing_dkim_selector_is_informational_not_a_failure(now: datetime) -> None:
    """We check a short documented list, never a wordlist. A custom selector
    is undiscoverable without enumeration, so absence is not a finding."""
    ctx = PluginContext.for_testing(snapshot=make_snapshot(dns=make_dns()), now=now)
    assert find(DnsPlugin().run(ctx).findings, "DNS-05").status is FindingStatus.INFO


# ================================================================ headers


def test_missing_security_headers_are_reported_individually(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(headers={"server": "nginx"}),)), now=now
    )
    result = HeadersPlugin().run(ctx)

    assert find(result.findings, "HDR-01").status is FindingStatus.FAIL  # HSTS
    assert find(result.findings, "HDR-02").status is FindingStatus.FAIL  # CSP
    assert "strict-transport-security" in result.artifacts["missing_headers"]


def test_a_fully_configured_site_passes_every_header_check(now: datetime) -> None:
    headers = {
        "strict-transport-security": "max-age=31536000",
        "content-security-policy": "default-src 'self'",
        "x-content-type-options": "nosniff",
        "x-frame-options": "SAMEORIGIN",
        "referrer-policy": "strict-origin",
        "permissions-policy": "geolocation=()",
    }
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(headers=headers),)), now=now
    )
    findings = HeadersPlugin().run(ctx).findings

    for check in ("HDR-01", "HDR-02", "HDR-03", "HDR-04", "HDR-05", "HDR-06"):
        assert find(findings, check).status is FindingStatus.PASS


def test_csp_frame_ancestors_satisfies_clickjacking_protection(now: datetime) -> None:
    """X-Frame-Options is not the only valid answer."""
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(
            pages=(make_page(headers={"content-security-policy": "frame-ancestors 'self'"}),)
        ),
        now=now,
    )
    assert find(HeadersPlugin().run(ctx).findings, "HDR-04").status is FindingStatus.PASS


def test_a_version_disclosing_banner_is_reported(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(headers={"x-powered-by": "PHP/7.4.3"}),)),
        now=now,
    )
    finding = find(HeadersPlugin().run(ctx).findings, "HDR-07")

    assert finding.status is FindingStatus.FAIL
    assert "x-powered-by" in finding.evidence["headers"]


def test_a_banner_without_a_version_is_not_flagged(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(headers={"server": "nginx"}),)), now=now
    )
    assert find(HeadersPlugin().run(ctx).findings, "HDR-07").status is FindingStatus.PASS


def test_insecure_cookies_are_reported(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(
            cookies=(CookieInfo(name="PHPSESSID", secure=False, http_only=False),)
        ),
        now=now,
    )
    findings = HeadersPlugin().run(ctx).findings

    assert find(findings, "CKY-01").status is FindingStatus.FAIL  # no Secure
    assert find(findings, "CKY-02").status is FindingStatus.WARN  # no HttpOnly


def test_no_cookies_means_the_cookie_checks_do_not_apply(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(cookies=()), now=now)
    findings = HeadersPlugin().run(ctx).findings

    for check in ("CKY-01", "CKY-02", "CKY-03"):
        assert find(findings, check).status is FindingStatus.NOT_APPLICABLE


def test_mixed_content_is_detected_on_https_pages(now: datetime) -> None:
    html = '<html><body><img src="http://cdn.example.com/logo.png"></body></html>'
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=(make_page(html=html),)), now=now)
    assert find(HeadersPlugin().run(ctx).findings, "CNT-01").status is FindingStatus.FAIL


def test_mixed_content_does_not_apply_to_http_sites(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(url="http://acme.com/", pages=(make_page("http://acme.com/"),)),
        now=now,
    )
    assert find(HeadersPlugin().run(ctx).findings, "CNT-01").status is FindingStatus.NOT_APPLICABLE


def test_a_cms_version_in_the_page_source_is_reported(now: datetime) -> None:
    html = '<meta name="generator" content="WordPress 5.4.2">'
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=(make_page(html=html),)), now=now)
    assert find(HeadersPlugin().run(ctx).findings, "CNT-02").status is FindingStatus.FAIL


def test_a_broken_page_makes_every_header_check_not_applicable(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=(make_page(status=500),)), now=now)
    findings = HeadersPlugin().run(ctx).findings

    for check in ("HDR-01", "HDR-02", "CKY-01", "CNT-01"):
        assert find(findings, check).status is FindingStatus.NOT_APPLICABLE


# ================================================================ performance


def test_a_slow_first_byte_is_reported_with_the_measurement(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(timings=Timings(ttfb_ms=3200, total_ms=5000)), now=now
    )
    finding = find(PerformancePlugin().run(ctx).findings, "PERF-01")

    assert finding.status is FindingStatus.FAIL
    assert finding.evidence["ttfb_ms"] == 3200


def test_a_fast_response_passes(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(timings=Timings(ttfb_ms=180, total_ms=600)), now=now
    )
    assert find(PerformancePlugin().run(ctx).findings, "PERF-01").status is FindingStatus.PASS


def test_a_missing_mobile_viewport_is_high_severity(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(html="<html><body>hi</body></html>"),)), now=now
    )
    finding = find(PerformancePlugin().run(ctx).findings, "PERF-04")

    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.HIGH


def test_a_declared_viewport_passes(now: datetime) -> None:
    html = '<html><head><meta name="viewport" content="width=device-width"></head></html>'
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=(make_page(html=html),)), now=now)
    assert find(PerformancePlugin().run(ctx).findings, "PERF-04").status is FindingStatus.PASS


def test_a_cdn_is_recognised_from_its_marker_header(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(headers={"cf-ray": "abc-LHR"}),)), now=now
    )
    result = PerformancePlugin().run(ctx)

    assert find(result.findings, "PERF-03").status is FindingStatus.PASS
    assert result.artifacts["has_cdn"] is True


def test_no_cdn_is_a_low_severity_observation(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(), now=now)
    finding = find(PerformancePlugin().run(ctx).findings, "PERF-03")

    assert finding.status is FindingStatus.WARN
    assert finding.severity is Severity.LOW
