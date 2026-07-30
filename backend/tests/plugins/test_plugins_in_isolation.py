"""Every plugin, tested alone.

No engine, no database, no network, no other plugin. This is the payoff of
the plugin boundary: each unit of analysis has a documented input, a
documented output, and no hidden collaborators.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import FindingStatus, Severity
from leadkhojo.plugins.base import PluginContext
from leadkhojo.plugins.builtin.cms_plugin import CmsPlugin
from leadkhojo.plugins.builtin.contacts_plugin import ContactsPlugin
from leadkhojo.plugins.builtin.dns_plugin import DnsPlugin
from leadkhojo.plugins.builtin.headers_plugin import HeadersPlugin
from leadkhojo.plugins.builtin.performance_plugin import PerformancePlugin
from leadkhojo.plugins.builtin.ssl_plugin import SslPlugin
from tests.conftest import make_dns, make_page, make_snapshot, make_tls


def find(findings: tuple[Finding, ...], check_id: str) -> Finding:
    for f in findings:
        if f.check_id == check_id:
            return f
    raise AssertionError(f"{check_id} not found in {[f.check_id for f in findings]}")


# ---------------------------------------------------------------- SSL


def test_expired_certificate_is_critical(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(tls=make_tls(days_until_expiry=-5)), now=now
    )
    result = SslPlugin().run(ctx)

    finding = find(result.findings, "TLS-03")
    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.CRITICAL
    assert finding.evidence["days_expired"] == 5
    assert finding.remediation


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
    result = SslPlugin().run(ctx)

    finding = find(result.findings, "TLS-04")
    assert finding.status is FindingStatus.FAIL
    assert finding.severity is expected
    assert finding.evidence["days_remaining"] == days


def test_healthy_certificate_passes(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(tls=make_tls(days_until_expiry=200)), now=now
    )
    result = SslPlugin().run(ctx)

    assert find(result.findings, "TLS-03").status is FindingStatus.PASS
    assert find(result.findings, "TLS-04").status is FindingStatus.PASS


def test_no_tls_yields_not_applicable_not_failure(now: datetime) -> None:
    """ "We could not check" is not "you failed". This distinction is the
    difference between a useful tool and one that makes false accusations."""
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(url="https://acme.com/", tls=None), now=now
    )
    result = SslPlugin().run(ctx)

    assert find(result.findings, "TLS-03").status is FindingStatus.NOT_APPLICABLE
    assert find(result.findings, "TLS-04").status is FindingStatus.NOT_APPLICABLE


def test_plain_http_site_is_critical(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(url="http://acme.com/", tls=None), now=now
    )
    result = SslPlugin().run(ctx)

    finding = find(result.findings, "TLS-01")
    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.CRITICAL


# ---------------------------------------------------------------- DNS


def test_missing_dmarc_is_a_failure_with_evidence(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(dns=make_dns(dmarc=None)), now=now)
    result = DnsPlugin().run(ctx)

    finding = find(result.findings, "DNS-03")
    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.HIGH
    assert finding.evidence["result"] == "NXDOMAIN"
    assert "acme.com" in finding.evidence["query"]


def test_dmarc_p_none_is_reported_separately(now: datetime) -> None:
    """Having DMARC and enforcing DMARC are different products to sell."""
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(dns=make_dns(dmarc="v=DMARC1; p=none; rua=mailto:x@acme.com")),
        now=now,
    )
    result = DnsPlugin().run(ctx)

    assert find(result.findings, "DNS-03").status is FindingStatus.PASS
    policy_finding = find(result.findings, "DNS-04")
    assert policy_finding.status is FindingStatus.FAIL
    assert policy_finding.evidence["policy"] == "none"


def test_permissive_spf_is_high_severity(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(dns=make_dns(spf="v=spf1 +all")), now=now
    )
    result = DnsPlugin().run(ctx)

    finding = find(result.findings, "DNS-02")
    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.HIGH


def test_no_dns_at_all_is_not_applicable(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(dns=None), now=now)
    result = DnsPlugin().run(ctx)

    for check in ("DNS-01", "DNS-03", "DNS-04"):
        assert find(result.findings, check).status is FindingStatus.NOT_APPLICABLE


# ---------------------------------------------------------------- headers


def test_missing_security_headers_are_reported(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(headers={"server": "nginx"}),)), now=now
    )
    result = HeadersPlugin().run(ctx)

    assert find(result.findings, "HDR-01").status is FindingStatus.FAIL  # HSTS
    assert find(result.findings, "HDR-02").status is FindingStatus.FAIL  # CSP
    assert "strict-transport-security" in result.artifacts["missing_headers"]


def test_present_headers_pass(now: datetime) -> None:
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
    result = HeadersPlugin().run(ctx)

    for check in ("HDR-01", "HDR-02", "HDR-03", "HDR-04", "HDR-05", "HDR-06"):
        assert find(result.findings, check).status is FindingStatus.PASS


# ---------------------------------------------------------------- CMS (has a dependency)


def test_cms_plugin_reads_a_stubbed_dependency(now: datetime) -> None:
    """THE point of the plugin boundary.

    To test `cms` we hand it a fake `technologies` artifact. The real
    technologies plugin never runs, so a bug there cannot fail this test.
    """
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(),
        now=now,
        artifacts={
            "technologies": {
                "technologies": [
                    {
                        "id": "wordpress",
                        "name": "WordPress",
                        "category": "cms",
                        "version": "5.4.2",
                        "confidence": "certain",
                        "is_outdated": True,
                        "versions_behind": 1,
                        "evidence": {"meta_generator": "WordPress 5.4.2"},
                    }
                ]
            }
        },
    )
    result = CmsPlugin().run(ctx)

    finding = find(result.findings, "CMS-02")
    assert finding.status is FindingStatus.FAIL
    assert finding.evidence["detected_version"] == "5.4.2"
    assert result.artifacts["cms"]["name"] == "WordPress"


def test_cms_without_a_version_says_nothing(now: datetime) -> None:
    """The specificity gate. "Your CMS might be old" is worse than silence."""
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(),
        now=now,
        artifacts={
            "technologies": {
                "technologies": [
                    {
                        "id": "wordpress",
                        "name": "WordPress",
                        "category": "cms",
                        "version": None,
                        "confidence": "certain",
                        "is_outdated": None,
                        "versions_behind": None,
                        "evidence": {},
                    }
                ]
            }
        },
    )
    result = CmsPlugin().run(ctx)
    assert find(result.findings, "CMS-02").status is FindingStatus.NOT_APPLICABLE


def test_cms_with_no_technologies_is_graceful(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(), now=now)
    result = CmsPlugin().run(ctx)
    assert result.artifacts["cms"] is None


# ---------------------------------------------------------------- performance


def test_missing_viewport_is_high_severity(now: datetime) -> None:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(html="<html><body>hi</body></html>"),)),
        now=now,
    )
    result = PerformancePlugin().run(ctx)

    finding = find(result.findings, "PERF-04")
    assert finding.status is FindingStatus.FAIL
    assert finding.severity is Severity.HIGH


def test_viewport_present_passes(now: datetime) -> None:
    html = '<html><head><meta name="viewport" content="width=device-width"></head></html>'
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=(make_page(html=html),)), now=now)
    result = PerformancePlugin().run(ctx)
    assert find(result.findings, "PERF-04").status is FindingStatus.PASS


# ---------------------------------------------------------------- contacts


def test_role_email_is_extracted_with_its_source(now: datetime) -> None:
    html = '<html><body><a href="mailto:info@acme.com">Email us</a></body></html>'
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=(make_page(html=html),)), now=now)
    result = ContactsPlugin().run(ctx)

    contacts = result.artifacts["contacts"]
    emails = [c for c in contacts if c["kind"] == "email"]
    assert len(emails) == 1
    assert emails[0]["value"] == "info@acme.com"
    assert emails[0]["source_url"] == "https://acme.com/"  # provenance is mandatory


def test_personal_and_freemail_addresses_are_rejected(now: datetime) -> None:
    html = """<html><body>
      <a href="mailto:john.smith@acme.com">John</a>
      <a href="mailto:someone@gmail.com">Personal</a>
      <a href="mailto:sales@acme.com">Sales</a>
    </body></html>"""
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=(make_page(html=html),)), now=now)
    result = ContactsPlugin().run(ctx)

    values = {c["value"] for c in result.artifacts["contacts"] if c["kind"] == "email"}
    assert values == {"sales@acme.com"}


def test_third_party_domain_email_is_rejected(now: datetime) -> None:
    """Found in the wild: django@fosstodon.org, a Mastodon handle that passes
    every naive filter and would be exported as the primary contact."""
    html = '<html><body><a href="mailto:acme@fosstodon.org">Follow us</a></body></html>'
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=(make_page(html=html),)), now=now)
    result = ContactsPlugin().run(ctx)
    assert not [c for c in result.artifacts["contacts"] if c["kind"] == "email"]


def test_no_contact_found_produces_nothing_not_a_guess(now: datetime) -> None:
    """The rule the whole module exists to enforce."""
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(html="<html><body>No contact</body></html>"),)),
        now=now,
    )
    result = ContactsPlugin().run(ctx)

    assert result.artifacts["primary_email"] is None
    assert result.artifacts["contact_count"] == 0
    # Specifically: we did NOT invent info@acme.com
    values = {c["value"] for c in result.artifacts["contacts"]}
    assert "info@acme.com" not in values


# ---------------------------------------------------------------- totality


@pytest.mark.parametrize(
    "plugin",
    [SslPlugin(), DnsPlugin(), HeadersPlugin(), PerformancePlugin(), ContactsPlugin(), CmsPlugin()],
    ids=lambda p: p.meta.id,
)
def test_every_plugin_survives_an_empty_snapshot(plugin, now: datetime) -> None:  # type: ignore[no-untyped-def]
    """Analyzers are total functions. One broken site must not stop a scan."""
    empty = make_snapshot(pages=(), tls=None, dns=None)
    result = plugin.run(PluginContext.for_testing(snapshot=empty, now=now))
    assert result.plugin_id == plugin.meta.id
