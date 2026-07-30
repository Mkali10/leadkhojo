"""Performance and mobile readiness — PERF-01..04.

Measured from timings and markup the crawler already captured. This is not a
synthetic benchmark; it is what one real visit looked like.
"""

from __future__ import annotations

import re
from typing import ClassVar

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import Severity
from leadkhojo.core.utils.clock import iso
from leadkhojo.plugins.base import BasePlugin, PluginContext, PluginKind, PluginMeta, PluginResult

PLUGIN_ID = "performance"
CATEGORY = "performance"

_VIEWPORT_RE = re.compile(r"""<meta[^>]+name\s*=\s*["']viewport["']""", re.IGNORECASE)
_LARGE_PAGE_BYTES = 3 * 1024 * 1024


class PerformancePlugin(BasePlugin):
    meta: ClassVar[PluginMeta] = PluginMeta(
        id=PLUGIN_ID,
        name="Performance & Mobile",
        version="1.0.0",
        kind=PluginKind.ANALYZER,
        description="Response time, page weight, CDN presence and mobile viewport.",
        provides=("timings", "has_cdn"),
        budget_ms=100,
    )

    def run(self, ctx: PluginContext) -> PluginResult:
        snap = ctx.snapshot
        home = snap.home

        if home is None or not home.is_ok:
            checks = ("PERF-01", "PERF-02", "PERF-03", "PERF-04")
            return self._result(
                tuple(
                    Finding.not_applicable(
                        c,
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        reason="No successful page response to measure",
                    )
                    for c in checks
                ),
                {"timings": {}, "has_cdn": False},
            )

        findings = [
            self._check_ttfb(ctx),
            self._check_page_weight(ctx),
            self._check_cdn(ctx),
            self._check_viewport(ctx),
        ]

        return self._result(
            tuple(findings),
            {
                "timings": {
                    "ttfb_ms": snap.timings.ttfb_ms,
                    "total_ms": snap.timings.total_ms,
                    "home_response_ms": home.response_time_ms,
                },
                "has_cdn": self._detect_cdn(ctx) is not None,
            },
        )

    # -- checks ------------------------------------------------------------

    def _check_ttfb(self, ctx: PluginContext) -> Finding:
        home = ctx.snapshot.home
        assert home is not None
        ttfb = ctx.snapshot.timings.ttfb_ms or home.response_time_ms
        threshold = ctx.settings.slow_ttfb_ms

        if ttfb <= 0:
            return Finding.not_applicable(
                "PERF-01",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="Response timing was not captured",
            )

        if ttfb > threshold:
            severity = Severity.MEDIUM if ttfb < threshold * 2 else Severity.HIGH
            return Finding.failed(
                "PERF-01",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=severity,
                title="Slow server response",
                description=(
                    f"The server took {ttfb} ms to send the first byte. Visitors "
                    "abandon pages that feel slow, and search ranking accounts for it."
                ),
                evidence={
                    "ttfb_ms": ttfb,
                    "threshold_ms": threshold,
                    "url": home.final_url,
                    "checked_at": iso(ctx.now),
                },
                remediation=(
                    "Add page caching, put a CDN in front of the site, or move to faster hosting."
                ),
            )

        return Finding.passed(
            "PERF-01",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title="Server responds quickly",
            evidence={"ttfb_ms": ttfb},
        )

    def _check_page_weight(self, ctx: PluginContext) -> Finding:
        home = ctx.snapshot.home
        assert home is not None
        size = home.bytes

        if size <= 0:
            return Finding.not_applicable(
                "PERF-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="Page size was not recorded",
            )

        if size > _LARGE_PAGE_BYTES:
            return Finding.warned(
                "PERF-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                severity=Severity.MEDIUM,
                title="Very large homepage",
                description=(
                    f"The homepage HTML alone is {size // 1024} KB. Large pages are "
                    "slow on mobile connections."
                ),
                evidence={"bytes": size, "url": home.final_url, "checked_at": iso(ctx.now)},
                remediation="Compress responses, defer non-critical assets and optimise images.",
            )

        return Finding.passed(
            "PERF-02",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title="Homepage size is reasonable",
            evidence={"bytes": size},
        )

    def _check_cdn(self, ctx: PluginContext) -> Finding:
        cdn = self._detect_cdn(ctx)
        if cdn:
            return Finding.passed(
                "PERF-03",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title=f"Content delivery network in use ({cdn})",
                evidence={"cdn": cdn},
            )
        return Finding.warned(
            "PERF-03",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.LOW,
            title="No CDN detected",
            description=(
                "The site does not appear to sit behind a content delivery network, so "
                "every visitor is served from the origin server regardless of where "
                "they are."
            ),
            evidence={
                "headers_checked": ["server", "via", "cf-ray", "x-cache"],
                "checked_at": iso(ctx.now),
            },
            remediation="Put a CDN (Cloudflare, Fastly, CloudFront) in front of the site.",
        )

    def _check_viewport(self, ctx: PluginContext) -> Finding:
        home = ctx.snapshot.home
        assert home is not None
        if not home.html:
            return Finding.not_applicable(
                "PERF-04",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason="No HTML to inspect",
            )

        if _VIEWPORT_RE.search(home.html):
            return Finding.passed(
                "PERF-04",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="Mobile viewport is configured",
            )

        return Finding.failed(
            "PERF-04",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.HIGH,
            title="No mobile viewport meta tag",
            description=(
                "The page does not declare a viewport, so mobile browsers render it at "
                "desktop width and zoom out. On a phone the site is close to unusable, "
                "and most local search traffic is mobile."
            ),
            evidence={"url": home.final_url, "checked_at": iso(ctx.now)},
            remediation=(
                'Add <meta name="viewport" content="width=device-width, initial-scale=1"> '
                "and verify the layout is responsive."
            ),
        )

    @staticmethod
    def _detect_cdn(ctx: PluginContext) -> str | None:
        headers = {k.lower(): (v or "").lower() for k, v in ctx.snapshot.all_headers().items()}

        if "cf-ray" in headers or "cloudflare" in headers.get("server", ""):
            return "Cloudflare"
        via = headers.get("via", "")
        if "cloudfront" in via or "cloudfront" in headers.get("x-cache", ""):
            return "CloudFront"
        if "fastly" in headers.get("x-served-by", "") or "fastly" in via:
            return "Fastly"
        if "akamai" in headers.get("server", "") or "akamai" in via:
            return "Akamai"
        if headers.get("x-vercel-id"):
            return "Vercel"
        if headers.get("x-nf-request-id"):
            return "Netlify"
        return None


__all__ = ["PLUGIN_ID", "PerformancePlugin"]
