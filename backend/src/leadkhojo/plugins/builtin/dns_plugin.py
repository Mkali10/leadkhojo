"""DNS / email-authentication plugin — checks DNS-01 through DNS-07.

Passive: ordinary public DNS resolution, already performed by the crawler.
No zone transfers, no subdomain enumeration.

The distinction that matters here: `snapshot.dns is None` means we never
looked, while `snapshot.dns.dmarc is None` means we looked and it was absent.
The first is NOT_APPLICABLE; the second is a genuine FAIL.
"""

from __future__ import annotations

import re
from typing import ClassVar

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import Severity
from leadkhojo.core.utils.clock import iso
from leadkhojo.plugins.base import BasePlugin, PluginContext, PluginKind, PluginMeta, PluginResult

CATEGORY = "email_auth"
PLUGIN_ID = "dns"

_DMARC_POLICY_RE = re.compile(r"\bp\s*=\s*(none|quarantine|reject)\b", re.IGNORECASE)
_SPF_ALL_RE = re.compile(r"([+\-~?])all\b", re.IGNORECASE)


class DnsPlugin(BasePlugin):
    meta: ClassVar[PluginMeta] = PluginMeta(
        id=PLUGIN_ID,
        name="DNS & Email Authentication",
        version="1.0.0",
        kind=PluginKind.ANALYZER,
        description="SPF, DMARC, DKIM, MX and DNSSEC posture from public DNS records.",
        provides=("spf", "dmarc", "mx", "dmarc_policy"),
        budget_ms=100,
    )

    def run(self, ctx: PluginContext) -> PluginResult:
        dns = ctx.snapshot.dns

        if dns is None:
            checks = ("DNS-01", "DNS-02", "DNS-03", "DNS-04", "DNS-05", "DNS-06", "DNS-07")
            return self._result(
                tuple(
                    Finding.not_applicable(
                        check,
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        reason="DNS records were not collected for this domain",
                    )
                    for check in checks
                ),
                {"spf": None, "dmarc": None, "mx": ()},
            )

        domain = ctx.snapshot.domain
        findings: list[Finding] = [
            self._check_spf_present(ctx, dns.spf, domain),
            self._check_spf_strictness(ctx, dns.spf),
            self._check_dmarc_present(ctx, dns.dmarc, domain),
            self._check_dmarc_policy(ctx, dns.dmarc, domain),
            self._check_dkim(ctx, dns.dkim_selectors),
            self._check_mx(ctx, dns.mx),
            self._check_dnssec(ctx, dns.dnssec),
        ]

        return self._result(
            tuple(findings),
            {
                "spf": dns.spf,
                "dmarc": dns.dmarc,
                "mx": list(dns.mx),
                "dmarc_policy": _dmarc_policy(dns.dmarc),
            },
        )

    # -- checks ------------------------------------------------------------

    def _check_spf_present(self, ctx: PluginContext, spf: str | None, domain: str) -> Finding:
        if spf:
            return Finding.passed(
                "DNS-01",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="SPF record is published",
                evidence={"record": spf},
            )
        return Finding.failed(
            "DNS-01",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.HIGH,
            title="No SPF record",
            description=(
                f"{domain} publishes no SPF record, so receiving mail servers have no "
                "way to tell which servers may send mail on its behalf. Anyone can "
                "send email that appears to come from this domain."
            ),
            evidence={
                "query": f"{domain} TXT",
                "result": "no v=spf1 record found",
                "checked_at": iso(ctx.now),
            },
            remediation=(
                f'Publish a TXT record at {domain} such as "v=spf1 include:_spf.'
                'yourprovider.com ~all", listing every service that sends mail for you.'
            ),
        )

    def _check_spf_strictness(self, ctx: PluginContext, spf: str | None) -> Finding:
        if not spf:
            return Finding.not_applicable(
                "DNS-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="No SPF record to evaluate (see DNS-01)",
            )

        match = _SPF_ALL_RE.search(spf)
        qualifier = match.group(1) if match else None

        if qualifier == "+":
            return Finding.failed(
                "DNS-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=Severity.HIGH,
                title="SPF record permits any sender",
                description=(
                    'The SPF record ends in "+all", which authorises every server on '
                    "the internet to send mail as this domain. That is equivalent to "
                    "having no SPF record at all, but harder to notice."
                ),
                evidence={"record": spf, "qualifier": "+all", "checked_at": iso(ctx.now)},
                remediation='Change "+all" to "~all" (softfail) or "-all" (hardfail).',
            )

        if qualifier == "?":
            # "?all" is neutral: it explicitly declines to make a statement,
            # so receiving servers treat unlisted senders exactly as they
            # would with no SPF record. Weaker than it looks.
            return Finding.warned(
                "DNS-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=Severity.MEDIUM,
                title="SPF record is neutral",
                description=(
                    'The SPF record ends in "?all" (neutral), which tells receiving '
                    "servers to make no judgement about unlisted senders. In practice "
                    "that offers no more protection than having no record at all."
                ),
                evidence={"record": spf, "qualifier": "?all", "checked_at": iso(ctx.now)},
                remediation='Change "?all" to "~all" (softfail) or "-all" (hardfail).',
            )

        if qualifier is None:
            return Finding.warned(
                "DNS-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=Severity.MEDIUM,
                title="SPF record has no all mechanism",
                description=(
                    "The SPF record does not end with an 'all' mechanism, so receiving "
                    "servers have no instruction for unlisted senders."
                ),
                evidence={"record": spf, "checked_at": iso(ctx.now)},
                remediation='Append "~all" or "-all" to the end of the record.',
            )

        return Finding.passed(
            "DNS-02",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title="SPF record is appropriately scoped",
            evidence={"record": spf, "qualifier": f"{qualifier}all"},
        )

    def _check_dmarc_present(self, ctx: PluginContext, dmarc: str | None, domain: str) -> Finding:
        if dmarc:
            return Finding.passed(
                "DNS-03",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="DMARC record is published",
                evidence={"record": dmarc},
            )
        return Finding.failed(
            "DNS-03",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.HIGH,
            title="No DMARC record",
            description=(
                f"{domain} publishes no DMARC record. Without one, receiving mail "
                "servers have no instruction on what to do with forged mail claiming "
                "to be from this domain, and the domain owner gets no reports of abuse."
            ),
            evidence={
                "query": f"_dmarc.{domain} TXT",
                "result": "NXDOMAIN",
                "checked_at": iso(ctx.now),
            },
            remediation=(
                f"Publish a TXT record at _dmarc.{domain} starting with "
                f'"v=DMARC1; p=none; rua=mailto:dmarc@{domain}" to begin collecting '
                "reports, then tighten to quarantine and finally reject."
            ),
        )

    def _check_dmarc_policy(self, ctx: PluginContext, dmarc: str | None, domain: str) -> Finding:
        if not dmarc:
            return Finding.not_applicable(
                "DNS-04",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="No DMARC record to evaluate (see DNS-03)",
            )

        policy = _dmarc_policy(dmarc)
        if policy is None:
            return Finding.warned(
                "DNS-04",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=Severity.MEDIUM,
                title="DMARC record has no policy",
                description="The DMARC record does not specify a p= policy.",
                evidence={"record": dmarc, "checked_at": iso(ctx.now)},
                remediation="Add a policy, e.g. p=quarantine.",
            )

        if policy == "none":
            return Finding.failed(
                "DNS-04",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=Severity.MEDIUM,
                title="DMARC policy is monitoring only",
                description=(
                    'The DMARC policy is "p=none", which collects reports but tells '
                    "receiving servers to deliver forged mail anyway. The domain is "
                    "observed but not protected."
                ),
                evidence={"record": dmarc, "policy": "none", "checked_at": iso(ctx.now)},
                remediation=(
                    "After reviewing DMARC reports, move to p=quarantine and then "
                    "p=reject to actually block spoofed mail."
                ),
            )

        return Finding.passed(
            "DNS-04",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title=f"DMARC policy is enforcing ({policy})",
            evidence={"record": dmarc, "policy": policy},
        )

    def _check_dkim(self, ctx: PluginContext, selectors: tuple[str, ...]) -> Finding:
        # Best-effort only: we query a small fixed list of documented selectors.
        # A custom selector is undiscoverable without enumeration, which we do
        # not do, so absence here is NOT a failure.
        if selectors:
            return Finding.passed(
                "DNS-05",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="DKIM signing key found",
                evidence={"selectors": list(selectors)},
            )
        return Finding.informational(
            "DNS-05",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title="No DKIM key found at common selectors",
            description=(
                "We check a short list of well-known selectors only. A domain using a "
                "custom selector will show no result here, so this is not a finding "
                "against the domain."
            ),
            evidence={"selectors_checked": ["default", "google", "k1", "selector1", "selector2"]},
        )

    def _check_mx(self, ctx: PluginContext, mx: tuple[str, ...]) -> Finding:
        if mx:
            return Finding.informational(
                "DNS-06",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="Domain receives email",
                evidence={"mx": list(mx)},
            )
        return Finding.informational(
            "DNS-06",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title="No MX records",
            description="This domain does not receive email directly.",
            evidence={"mx": []},
        )

    def _check_dnssec(self, ctx: PluginContext, dnssec: bool) -> Finding:
        if dnssec:
            return Finding.passed(
                "DNS-07",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="DNSSEC is enabled",
                evidence={"dnssec": True},
            )
        return Finding.warned(
            "DNS-07",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.LOW,
            title="DNSSEC is not enabled",
            description=(
                "DNS responses for this domain are not cryptographically signed, so a "
                "resolver cannot detect tampering."
            ),
            evidence={"dnssec": False, "checked_at": iso(ctx.now)},
            remediation="Enable DNSSEC signing at your DNS provider and publish a DS record.",
        )


def _dmarc_policy(record: str | None) -> str | None:
    if not record:
        return None
    match = _DMARC_POLICY_RE.search(record)
    return match.group(1).lower() if match else None


__all__ = ["PLUGIN_ID", "DnsPlugin"]
