"""HTTP security headers and cookies — HDR-01..07, CKY-01..03, CNT-01/02.

Passive: every header assessed here was sent by the server in response to the
ordinary page request the crawler already made.
"""

from __future__ import annotations

import re
from typing import ClassVar

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import Severity
from leadkhojo.core.utils.clock import iso
from leadkhojo.plugins.base import BasePlugin, PluginContext, PluginKind, PluginMeta, PluginResult

CATEGORY = "headers"
COOKIE_CATEGORY = "cookies"
CONTENT_CATEGORY = "content"
PLUGIN_ID = "headers"

_VERSION_IN_BANNER = re.compile(r"\d+\.\d+")
_MIXED_CONTENT_RE = re.compile(
    r"""(?:src|href)\s*=\s*["']http://(?!localhost|127\.0\.0\.1)""", re.IGNORECASE
)
_GENERATOR_RE = re.compile(
    r"""<meta[^>]+name\s*=\s*["']generator["'][^>]+content\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)

# (check_id, header, severity, title, why it matters, what to do)
_HEADER_CHECKS: tuple[tuple[str, str, Severity, str, str, str], ...] = (
    (
        "HDR-01",
        "strict-transport-security",
        Severity.HIGH,
        "HSTS header missing",
        "Without HSTS a visitor's first request can be downgraded to HTTP and "
        "intercepted, even though the site supports HTTPS.",
        "Add: Strict-Transport-Security: max-age=31536000; includeSubDomains",
    ),
    (
        "HDR-02",
        "content-security-policy",
        Severity.HIGH,
        "Content-Security-Policy header missing",
        "There is no policy restricting where scripts may load from, so an injected "
        "script has no additional barrier to running.",
        "Add a Content-Security-Policy header, starting in report-only mode.",
    ),
    (
        "HDR-03",
        "x-content-type-options",
        Severity.MEDIUM,
        "X-Content-Type-Options header missing",
        "Browsers may guess a response's content type, which can turn an uploaded "
        "file into executable script.",
        "Add: X-Content-Type-Options: nosniff",
    ),
    (
        "HDR-05",
        "referrer-policy",
        Severity.LOW,
        "Referrer-Policy header missing",
        "Full URLs are sent to third-party sites in the Referer header, which can "
        "leak internal paths and query parameters.",
        "Add: Referrer-Policy: strict-origin-when-cross-origin",
    ),
    (
        "HDR-06",
        "permissions-policy",
        Severity.LOW,
        "Permissions-Policy header missing",
        "Embedded content is not restricted from requesting camera, microphone or "
        "geolocation access.",
        "Add a Permissions-Policy header disabling features the site does not use.",
    ),
)


class HeadersPlugin(BasePlugin):
    meta: ClassVar[PluginMeta] = PluginMeta(
        id=PLUGIN_ID,
        name="Security Headers & Cookies",
        version="1.0.0",
        kind=PluginKind.ANALYZER,
        description="HTTP security headers, cookie flags, mixed content and version disclosure.",
        provides=("security_headers", "missing_headers"),
        budget_ms=400,
    )

    def run(self, ctx: PluginContext) -> PluginResult:
        home = ctx.snapshot.home
        if home is None or not home.is_ok:
            checks = [c[0] for c in _HEADER_CHECKS] + [
                "HDR-04",
                "HDR-07",
                "CKY-01",
                "CKY-02",
                "CKY-03",
                "CNT-01",
                "CNT-02",
            ]
            return self._result(
                tuple(
                    Finding.not_applicable(
                        check,
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        reason="No successful page response to inspect",
                    )
                    for check in checks
                ),
                {"security_headers": {}, "missing_headers": []},
            )

        headers = {k.lower(): v for k, v in home.headers.items()}
        findings: list[Finding] = []
        missing: list[str] = []

        for check_id, header, severity, title, why, fix in _HEADER_CHECKS:
            value = headers.get(header)
            if value:
                findings.append(
                    Finding.passed(
                        check_id,
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        title=f"{header} is set",
                        evidence={"header": header, "value": value[:200]},
                    )
                )
            else:
                missing.append(header)
                findings.append(
                    Finding.failed(
                        check_id,
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        severity=severity,
                        title=title,
                        description=why,
                        evidence={
                            "header": header,
                            "present": False,
                            "url": home.final_url,
                            "checked_at": iso(ctx.now),
                        },
                        remediation=fix,
                    )
                )

        findings.append(self._check_framing(ctx, headers, home.final_url, missing))
        findings.append(self._check_version_disclosure(ctx, headers))
        findings.extend(self._check_cookies(ctx))
        findings.append(self._check_mixed_content(ctx))
        findings.append(self._check_generator(ctx))
        findings.extend(self._check_privacy(ctx))

        return self._result(
            tuple(findings),
            {
                "security_headers": {
                    h: headers.get(h)
                    for h in (
                        "strict-transport-security",
                        "content-security-policy",
                        "x-content-type-options",
                        "x-frame-options",
                        "referrer-policy",
                        "permissions-policy",
                    )
                },
                "missing_headers": missing,
            },
        )

    # -- checks ------------------------------------------------------------

    def _check_framing(
        self,
        ctx: PluginContext,
        headers: dict[str, str],
        url: str,
        missing: list[str],
    ) -> Finding:
        xfo = headers.get("x-frame-options")
        csp = headers.get("content-security-policy", "")
        has_ancestors = "frame-ancestors" in csp.lower()

        if xfo or has_ancestors:
            return Finding.passed(
                "HDR-04",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="Clickjacking protection is present",
                evidence={
                    "x_frame_options": xfo,
                    "csp_frame_ancestors": has_ancestors,
                },
            )

        missing.append("x-frame-options")
        return Finding.failed(
            "HDR-04",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.MEDIUM,
            title="No clickjacking protection",
            description=(
                "Neither X-Frame-Options nor a CSP frame-ancestors directive is set, "
                "so the site can be embedded in a hostile page and used to trick "
                "visitors into clicking things they cannot see."
            ),
            evidence={"url": url, "present": False, "checked_at": iso(ctx.now)},
            remediation="Add: X-Frame-Options: SAMEORIGIN, or a CSP frame-ancestors directive.",
        )

    def _check_version_disclosure(self, ctx: PluginContext, headers: dict[str, str]) -> Finding:
        disclosed: dict[str, str] = {}
        for header in ("server", "x-powered-by", "x-aspnet-version", "x-generator"):
            value = headers.get(header)
            if value and _VERSION_IN_BANNER.search(value):
                disclosed[header] = value

        if not disclosed:
            return Finding.passed(
                "HDR-07",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="No software versions disclosed in headers",
            )

        return Finding.failed(
            "HDR-07",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.LOW,
            title="Software version disclosed in response headers",
            description=(
                "Response headers name the exact software version in use, which tells "
                "an attacker which published vulnerabilities to try first."
            ),
            evidence={"headers": disclosed, "checked_at": iso(ctx.now)},
            remediation=(
                "Suppress version numbers: server_tokens off (nginx), "
                "ServerTokens Prod (Apache), or remove the X-Powered-By header."
            ),
        )

    def _check_cookies(self, ctx: PluginContext) -> list[Finding]:
        cookies = ctx.snapshot.cookies
        if not cookies:
            return [
                Finding.not_applicable(
                    check,
                    plugin_id=PLUGIN_ID,
                    category=COOKIE_CATEGORY,
                    reason="No cookies were set by the site",
                )
                for check in ("CKY-01", "CKY-02", "CKY-03")
            ]

        insecure = [c.name for c in cookies if not c.secure]
        no_http_only = [c.name for c in cookies if not c.http_only]
        no_same_site = [c.name for c in cookies if not c.same_site]

        findings: list[Finding] = []

        if insecure and ctx.snapshot.is_https:
            findings.append(
                Finding.failed(
                    "CKY-01",
                    plugin_id=PLUGIN_ID,
                    category=COOKIE_CATEGORY,
                    severity=Severity.MEDIUM,
                    title="Cookies set without the Secure flag",
                    description=(
                        f"{len(insecure)} cookie(s) may be transmitted over plain HTTP, "
                        "where they can be read in transit."
                    ),
                    evidence={"cookies": insecure[:10], "checked_at": iso(ctx.now)},
                    remediation="Add the Secure attribute to every cookie on an HTTPS site.",
                )
            )
        else:
            findings.append(
                Finding.passed(
                    "CKY-01",
                    plugin_id=PLUGIN_ID,
                    category=COOKIE_CATEGORY,
                    title="All cookies use the Secure flag",
                    evidence={"cookie_count": len(cookies)},
                )
            )

        if no_http_only:
            findings.append(
                Finding.warned(
                    "CKY-02",
                    plugin_id=PLUGIN_ID,
                    category=COOKIE_CATEGORY,
                    severity=Severity.MEDIUM,
                    title="Cookies readable by JavaScript",
                    description=(
                        f"{len(no_http_only)} cookie(s) lack HttpOnly, so any script on "
                        "the page — including an injected one — can read them."
                    ),
                    evidence={"cookies": no_http_only[:10], "checked_at": iso(ctx.now)},
                    remediation="Add HttpOnly to cookies that JavaScript does not need to read.",
                )
            )
        else:
            findings.append(
                Finding.passed(
                    "CKY-02",
                    plugin_id=PLUGIN_ID,
                    category=COOKIE_CATEGORY,
                    title="Cookies are not exposed to JavaScript",
                )
            )

        if no_same_site:
            findings.append(
                Finding.warned(
                    "CKY-03",
                    plugin_id=PLUGIN_ID,
                    category=COOKIE_CATEGORY,
                    severity=Severity.LOW,
                    title="Cookies without SameSite",
                    description=(
                        f"{len(no_same_site)} cookie(s) do not set SameSite, leaving "
                        "them attached to cross-site requests."
                    ),
                    evidence={"cookies": no_same_site[:10], "checked_at": iso(ctx.now)},
                    remediation="Set SameSite=Lax (or Strict) on cookies.",
                )
            )
        else:
            findings.append(
                Finding.passed(
                    "CKY-03",
                    plugin_id=PLUGIN_ID,
                    category=COOKIE_CATEGORY,
                    title="All cookies set SameSite",
                )
            )

        return findings

    def _check_mixed_content(self, ctx: PluginContext) -> Finding:
        if not ctx.snapshot.is_https:
            return Finding.not_applicable(
                "CNT-01",
                plugin_id=PLUGIN_ID,
                category=CONTENT_CATEGORY,
                reason="Site is not served over HTTPS, so mixed content does not apply",
            )

        offenders: list[str] = []
        for page in ctx.snapshot.pages:
            if page.html and _MIXED_CONTENT_RE.search(page.html):
                offenders.append(page.final_url)

        if not offenders:
            return Finding.passed(
                "CNT-01",
                plugin_id=PLUGIN_ID,
                category=CONTENT_CATEGORY,
                title="No mixed content detected",
            )

        return Finding.failed(
            "CNT-01",
            plugin_id=PLUGIN_ID,
            category=CONTENT_CATEGORY,
            severity=Severity.MEDIUM,
            title="Mixed content on HTTPS pages",
            description=(
                "Pages served over HTTPS load resources over plain HTTP. Browsers "
                "block or downgrade these, which breaks styling and functionality and "
                "removes the padlock."
            ),
            evidence={"pages": offenders[:5], "checked_at": iso(ctx.now)},
            remediation="Update asset URLs to https:// or protocol-relative paths.",
        )

    def _check_generator(self, ctx: PluginContext) -> Finding:
        home = ctx.snapshot.home
        if home is None or not home.html:
            return Finding.not_applicable(
                "CNT-02",
                plugin_id=PLUGIN_ID,
                category=CONTENT_CATEGORY,
                reason="No HTML to inspect",
            )

        match = _GENERATOR_RE.search(home.html)
        if not match:
            return Finding.passed(
                "CNT-02",
                plugin_id=PLUGIN_ID,
                category=CONTENT_CATEGORY,
                title="No CMS version disclosed in page source",
            )

        generator = match.group(1).strip()
        if not _VERSION_IN_BANNER.search(generator):
            return Finding.passed(
                "CNT-02",
                plugin_id=PLUGIN_ID,
                category=CONTENT_CATEGORY,
                title="Generator tag present but discloses no version",
                evidence={"generator": generator},
            )

        return Finding.failed(
            "CNT-02",
            plugin_id=PLUGIN_ID,
            category=CONTENT_CATEGORY,
            severity=Severity.LOW,
            title="CMS version disclosed in page source",
            description=(
                f'The page publishes its exact software version ("{generator}") in a '
                "meta tag, which tells an attacker which published vulnerabilities "
                "to try first."
            ),
            evidence={
                "generator": generator,
                "url": home.final_url,
                "checked_at": iso(ctx.now),
            },
            remediation="Remove the generator meta tag, or strip the version from it.",
        )

    def _check_privacy(self, ctx: PluginContext) -> list[Finding]:
        """Privacy signals: PRV-01 privacy policy, PRV-02 cookie banner.

        PRV-02 deliberately does not decide whether a banner is *required* —
        that depends on jurisdiction and on what the scripts actually do. It
        reports the observable combination and leaves the judgement to a human.
        """
        html_blob = "\n".join(ctx.snapshot.html_documents()).lower()
        findings: list[Finding] = []

        has_policy = bool(
            re.search(r"(privacy[-\s]?policy|privacy[-_]?notice|/privacy)", html_blob)
        )
        findings.append(
            Finding.informational(
                "PRV-01",
                plugin_id=PLUGIN_ID,
                category=CONTENT_CATEGORY,
                title="Privacy policy link found" if has_policy else "No privacy policy link found",
                evidence={"found": has_policy},
            )
        )

        if not html_blob:
            findings.append(
                Finding.not_applicable(
                    "PRV-02",
                    plugin_id=PLUGIN_ID,
                    category=CONTENT_CATEGORY,
                    reason="No HTML to inspect",
                )
            )
            return findings

        has_banner = bool(
            re.search(
                r"(cookie[-\s]?(consent|banner|notice|policy)|cookieconsent|gdpr|"
                r"onetrust|cookiebot|termly|iubenda|klaro|didomi)",
                html_blob,
            )
        )

        if has_banner:
            findings.append(
                Finding.passed(
                    "PRV-02",
                    plugin_id=PLUGIN_ID,
                    category=CONTENT_CATEGORY,
                    title="Cookie consent mechanism detected",
                    evidence={"found": True},
                )
            )
        else:
            findings.append(
                Finding.warned(
                    "PRV-02",
                    plugin_id=PLUGIN_ID,
                    category=CONTENT_CATEGORY,
                    severity=Severity.LOW,
                    title="No cookie consent mechanism detected",
                    description=(
                        "No cookie consent banner or consent-management platform was "
                        "found in the page source."
                    ),
                    evidence={"found": False, "checked_at": iso(ctx.now)},
                    remediation=(
                        "If third-party tracking runs before consent, add a consent "
                        "banner. Confirm the specific requirement with a legal advisor."
                    ),
                )
            )

        return findings


__all__ = ["PLUGIN_ID", "HeadersPlugin"]
