"""CMS plugin.

Depends on `technologies`. Note what that means in practice: this file does
NOT import the technologies plugin. It declares `depends_on=("technologies",)`
and reads the published artifact through the context.

That indirection is the whole point — the engine can order, skip, or stub the
dependency, and this plugin is testable by handing it a fake artifact.
"""

from __future__ import annotations

from typing import Any, ClassVar

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import Severity
from leadkhojo.core.utils.clock import iso
from leadkhojo.plugins.base import BasePlugin, PluginContext, PluginKind, PluginMeta, PluginResult

PLUGIN_ID = "cms"
CATEGORY = "cms"

# Paths that a CMS conventionally publishes. We only look at what the crawler
# already fetched — this is not path enumeration.
_ADMIN_PATHS: dict[str, str] = {
    "wordpress": "/wp-login.php",
    "drupal": "/user/login",
    "joomla": "/administrator",
    "magento": "/admin",
}


class CmsPlugin(BasePlugin):
    meta: ClassVar[PluginMeta] = PluginMeta(
        id=PLUGIN_ID,
        name="CMS Analysis",
        version="1.0.0",
        kind=PluginKind.ANALYZER,
        description="CMS identification, version currency and admin exposure.",
        depends_on=("technologies",),
        provides=("cms",),
        budget_ms=100,
    )

    def run(self, ctx: PluginContext) -> PluginResult:
        technologies: list[dict[str, Any]] = ctx.artifact("technologies", "technologies", []) or []
        cms_entries = [t for t in technologies if t.get("category") in ("cms", "ecommerce")]

        if not cms_entries:
            return self._result(
                (
                    Finding.informational(
                        "CMS-01",
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        title="No CMS detected",
                        description=(
                            "The site does not appear to use a recognised content "
                            "management system. It may be custom-built or static."
                        ),
                        evidence={"technologies_checked": len(technologies)},
                    ),
                ),
                {"cms": None},
            )

        # Highest-confidence CMS wins; ties broken alphabetically for determinism.
        primary = sorted(
            cms_entries,
            key=lambda t: (
                {"certain": 0, "likely": 1, "possible": 2}.get(t.get("confidence", "possible"), 3),
                str(t.get("id", "")),
            ),
        )[0]

        findings: list[Finding] = [
            Finding.informational(
                "CMS-01",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title=f"{primary['name']} detected",
                evidence={
                    "cms": primary["name"],
                    "version": primary.get("version"),
                    "confidence": primary.get("confidence"),
                    "detection": primary.get("evidence", {}),
                },
            )
        ]

        findings.append(self._check_version_known(ctx, primary))
        findings.append(self._check_admin_exposure(ctx, primary))

        return self._result(tuple(findings), {"cms": primary})

    # -- checks ------------------------------------------------------------

    def _check_version_known(self, ctx: PluginContext, cms: dict[str, Any]) -> Finding:
        """Is the CMS version knowable, and is it current?

        This is where the specificity gate lives. An unknown version yields
        NOT_APPLICABLE — never a vague "your CMS might be outdated", which is
        exactly the generic filler that makes a whole report untrustworthy.
        """
        version = cms.get("version")
        if not version:
            return Finding.not_applicable(
                "CMS-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason=(
                    f"{cms['name']} was detected but does not disclose its version, "
                    "so currency cannot be assessed"
                ),
            )

        outdated = cms.get("is_outdated")
        if outdated is None:
            return Finding.not_applicable(
                "CMS-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason=f"No reference version on file for {cms['name']}",
            )

        if not outdated:
            return Finding.passed(
                "CMS-02",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title=f"{cms['name']} {version} is current",
                evidence={"cms": cms["name"], "version": version},
            )

        behind = cms.get("versions_behind") or 0
        severity = Severity.HIGH if behind >= 2 else Severity.MEDIUM
        return Finding.failed(
            "CMS-02",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=severity,
            title=f"{cms['name']} {version} is outdated",
            description=(
                f"The site runs {cms['name']} {version}"
                + (f", {behind} major release(s) behind current" if behind else "")
                + ". Outdated releases stop receiving security fixes, and the version "
                "is published in the page source where anyone can read it."
            ),
            evidence={
                "cms": cms["name"],
                "detected_version": version,
                "versions_behind": behind,
                "detection": cms.get("evidence", {}),
                "checked_at": iso(ctx.now),
            },
            remediation=(
                f"Upgrade {cms['name']} to the current release and put a regular "
                "patching schedule in place."
            ),
        )

    def _check_admin_exposure(self, ctx: PluginContext, cms: dict[str, Any]) -> Finding:
        """Was a login page served over plain HTTP?

        We do not go looking for admin pages. We only report on one if the
        crawler happened to fetch it and it was insecure.
        """
        cms_id = str(cms.get("id", ""))
        expected_path = _ADMIN_PATHS.get(cms_id)
        if not expected_path:
            return Finding.not_applicable(
                "CMS-03",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                reason=f"No known admin path convention for {cms.get('name')}",
            )

        for page in ctx.snapshot.pages:
            if expected_path in page.final_url and page.final_url.startswith("http://"):
                return Finding.failed(
                    "CMS-03",
                    plugin_id=PLUGIN_ID,
                    category=CATEGORY,
                    severity=Severity.CRITICAL,
                    title="Admin login served over plain HTTP",
                    description=(
                        "The administrator login page is served without encryption, so "
                        "credentials typed into it travel in the clear."
                    ),
                    evidence={
                        "url": page.final_url,
                        "cms": cms.get("name"),
                        "checked_at": iso(ctx.now),
                    },
                    remediation="Force HTTPS on all admin paths and redirect HTTP to HTTPS.",
                )

        return Finding.not_applicable(
            "CMS-03",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            reason="The admin path was not among the pages fetched",
        )


__all__ = ["PLUGIN_ID", "CmsPlugin"]
