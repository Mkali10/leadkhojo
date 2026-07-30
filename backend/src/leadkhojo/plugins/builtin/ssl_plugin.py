"""SSL/TLS plugin — checks TLS-01 through TLS-08.

Passive: every fact here comes from the TLS handshake the crawler already
completed in order to load the page. Nothing is probed.
"""

from __future__ import annotations

from typing import ClassVar

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import Severity
from leadkhojo.core.utils.clock import days_between, iso
from leadkhojo.core.utils.versions import Version
from leadkhojo.plugins.base import BasePlugin, PluginContext, PluginKind, PluginMeta, PluginResult

CATEGORY = "tls"
PLUGIN_ID = "ssl"


class SslPlugin(BasePlugin):
    meta: ClassVar[PluginMeta] = PluginMeta(
        id=PLUGIN_ID,
        name="SSL / TLS",
        version="1.0.0",
        kind=PluginKind.ANALYZER,
        description="Certificate validity, expiry, hostname match and protocol version.",
        provides=("certificate",),
        budget_ms=100,
    )

    def run(self, ctx: PluginContext) -> PluginResult:
        snap = ctx.snapshot
        findings: list[Finding] = []

        # TLS-01: is HTTPS available at all?
        if not snap.is_https:
            findings.append(
                Finding.failed(
                    "TLS-01",
                    plugin_id=PLUGIN_ID,
                    category=CATEGORY,
                    severity=Severity.CRITICAL,
                    title="Site is not served over HTTPS",
                    description=(
                        "The site is served over plain HTTP. Browsers mark it "
                        '"Not secure", and anything a visitor types travels in the clear.'
                    ),
                    evidence={
                        "final_url": snap.final_url or snap.requested_url,
                        "checked_at": iso(ctx.now),
                    },
                    remediation=(
                        "Install a TLS certificate (Let's Encrypt is free) and "
                        "redirect all HTTP traffic to HTTPS."
                    ),
                )
            )
            # Every other TLS check needs a certificate we do not have.
            for check in ("TLS-02", "TLS-03", "TLS-04", "TLS-05", "TLS-06", "TLS-07", "TLS-08"):
                findings.append(
                    Finding.not_applicable(
                        check,
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        reason="No HTTPS connection was established",
                    )
                )
            return self._result(tuple(findings), {"certificate": None})

        findings.append(
            Finding.passed(
                "TLS-01",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="HTTPS is available",
                evidence={"final_url": snap.final_url or snap.requested_url},
            )
        )

        # TLS-02: does HTTP redirect to HTTPS?
        findings.append(self._check_http_redirect(ctx))

        tls = snap.tls
        if tls is None:
            for check in ("TLS-03", "TLS-04", "TLS-05", "TLS-06", "TLS-07", "TLS-08"):
                findings.append(
                    Finding.not_applicable(
                        check,
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        reason="Certificate details were not captured",
                    )
                )
            return self._result(tuple(findings), {"certificate": None})

        findings.append(self._check_validity(ctx))
        findings.append(self._check_expiry(ctx))
        findings.append(self._check_hostname(ctx))
        findings.append(self._check_protocol(ctx))
        findings.append(self._check_chain(ctx))
        findings.append(self._check_self_signed(ctx))

        certificate = {
            "issuer": tls.issuer,
            "subject": tls.subject,
            "not_after": iso(tls.not_after) if tls.not_after else None,
            "days_remaining": (days_between(ctx.now, tls.not_after) if tls.not_after else None),
            "protocol": tls.protocol,
        }
        return self._result(tuple(findings), {"certificate": certificate})

    # -- individual checks -------------------------------------------------

    def _check_http_redirect(self, ctx: PluginContext) -> Finding:
        chain = ctx.snapshot.redirect_chain
        upgraded = any(u.startswith("http://") for u in chain) and ctx.snapshot.is_https
        if ctx.snapshot.requested_url.startswith("https://") and not chain:
            return Finding.not_applicable(
                "TLS-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="Site was requested over HTTPS directly; no HTTP redirect observed",
            )
        if upgraded:
            return Finding.passed(
                "TLS-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="HTTP redirects to HTTPS",
                evidence={"redirect_chain": list(chain)},
            )
        return Finding.failed(
            "TLS-02",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.HIGH,
            title="HTTP does not redirect to HTTPS",
            description=(
                "Visitors arriving over HTTP are not upgraded to HTTPS, so their "
                "first request travels unencrypted."
            ),
            evidence={"redirect_chain": list(chain), "checked_at": iso(ctx.now)},
            remediation="Add a permanent (301) redirect from http:// to https:// for all paths.",
        )

    def _check_validity(self, ctx: PluginContext) -> Finding:
        tls = ctx.snapshot.tls
        assert tls is not None
        if tls.not_after is None:
            return Finding.not_applicable(
                "TLS-03",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="Certificate has no expiry date",
            )

        days = days_between(ctx.now, tls.not_after)
        if days < 0:
            return Finding.failed(
                "TLS-03",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=Severity.CRITICAL,
                title="SSL certificate has expired",
                description=(
                    f"The certificate expired on {iso(tls.not_after)[:10]}, "
                    f"{abs(days)} days ago. Every visitor sees a full-page browser "
                    "security warning."
                ),
                evidence={
                    "not_after": iso(tls.not_after),
                    "days_expired": abs(days),
                    "issuer": tls.issuer,
                    "checked_at": iso(ctx.now),
                },
                remediation="Renew the certificate immediately and enable automatic ACME renewal.",
            )

        if tls.not_before and days_between(tls.not_before, ctx.now) < 0:
            return Finding.failed(
                "TLS-03",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=Severity.CRITICAL,
                title="SSL certificate is not yet valid",
                description="The certificate's start date is in the future.",
                evidence={"not_before": iso(tls.not_before), "checked_at": iso(ctx.now)},
                remediation="Check the server clock and reissue the certificate.",
            )

        return Finding.passed(
            "TLS-03",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title="SSL certificate is valid",
            evidence={"not_after": iso(tls.not_after), "days_remaining": days},
        )

    def _check_expiry(self, ctx: PluginContext) -> Finding:
        tls = ctx.snapshot.tls
        assert tls is not None
        if tls.not_after is None:
            return Finding.not_applicable(
                "TLS-04",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="Certificate has no expiry date",
            )

        days = days_between(ctx.now, tls.not_after)
        if days < 0:
            return Finding.not_applicable(
                "TLS-04",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="Certificate has already expired (see TLS-03)",
            )

        warn_days = ctx.settings.cert_expiry_warn_days
        if days < warn_days:
            severity = Severity.CRITICAL if days <= 7 else Severity.HIGH
            return Finding.failed(
                "TLS-04",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=severity,
                title="SSL certificate expires soon",
                description=(
                    f"The certificate expires on {iso(tls.not_after)[:10]} — in {days} "
                    "days. When it lapses, every visitor sees a full-page browser "
                    "security warning and the site is effectively offline for most users."
                ),
                evidence={
                    "not_after": iso(tls.not_after),
                    "days_remaining": days,
                    "issuer": tls.issuer,
                    "checked_at": iso(ctx.now),
                },
                remediation=(
                    "Renew the certificate and enable automatic renewal via ACME "
                    "(Let's Encrypt, ZeroSSL) so this cannot recur."
                ),
            )

        return Finding.passed(
            "TLS-04",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title="SSL certificate is not expiring soon",
            evidence={"days_remaining": days, "not_after": iso(tls.not_after)},
        )

    def _check_hostname(self, ctx: PluginContext) -> Finding:
        tls = ctx.snapshot.tls
        assert tls is not None
        if tls.hostname_matches:
            return Finding.passed(
                "TLS-05",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="Certificate matches the hostname",
                evidence={"subject": tls.subject, "sans": list(tls.sans)},
            )
        return Finding.failed(
            "TLS-05",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.CRITICAL,
            title="Certificate does not match the hostname",
            description=(
                "The certificate is issued for a different name, so browsers show a "
                "security warning before the page loads."
            ),
            evidence={
                "hostname": ctx.snapshot.domain,
                "subject": tls.subject,
                "sans": list(tls.sans),
                "checked_at": iso(ctx.now),
            },
            remediation="Reissue the certificate including this hostname in the SAN list.",
        )

    def _check_protocol(self, ctx: PluginContext) -> Finding:
        tls = ctx.snapshot.tls
        assert tls is not None
        if not tls.protocol:
            return Finding.not_applicable(
                "TLS-06",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="Negotiated protocol was not captured",
            )

        # "TLSv1.3" -> 1.3
        numeric = tls.protocol.upper().replace("TLSV", "").strip()
        version = Version(numeric)
        if version.is_valid and version < Version("1.2"):
            return Finding.failed(
                "TLS-06",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=Severity.HIGH,
                title="Outdated TLS protocol version",
                description=(
                    f"The server negotiated {tls.protocol}. TLS below 1.2 is deprecated "
                    "and rejected by current browsers."
                ),
                evidence={"protocol": tls.protocol, "checked_at": iso(ctx.now)},
                remediation="Enable TLS 1.2 and 1.3 and disable TLS 1.0 and 1.1.",
            )

        return Finding.passed(
            "TLS-06",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title="Modern TLS protocol in use",
            evidence={"protocol": tls.protocol},
        )

    def _check_chain(self, ctx: PluginContext) -> Finding:
        tls = ctx.snapshot.tls
        assert tls is not None
        if tls.chain_complete:
            return Finding.passed(
                "TLS-07",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="Certificate chain is complete",
            )
        return Finding.failed(
            "TLS-07",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.MEDIUM,
            title="Incomplete certificate chain",
            description=(
                "The server does not send the full intermediate chain. Some clients — "
                "particularly older mobile devices — will refuse the connection."
            ),
            evidence={"issuer": tls.issuer, "checked_at": iso(ctx.now)},
            remediation="Configure the server to send the full chain including intermediates.",
        )

    def _check_self_signed(self, ctx: PluginContext) -> Finding:
        tls = ctx.snapshot.tls
        assert tls is not None
        if not tls.is_self_signed:
            return Finding.passed(
                "TLS-08",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="Certificate is issued by a recognised authority",
                evidence={"issuer": tls.issuer},
            )
        return Finding.failed(
            "TLS-08",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.HIGH,
            title="Self-signed certificate",
            description=(
                "The certificate is self-signed, so every browser shows a security "
                "warning before the page loads."
            ),
            evidence={"issuer": tls.issuer, "subject": tls.subject, "checked_at": iso(ctx.now)},
            remediation="Replace with a certificate from a trusted CA (Let's Encrypt is free).",
        )


__all__ = ["PLUGIN_ID", "SslPlugin"]
