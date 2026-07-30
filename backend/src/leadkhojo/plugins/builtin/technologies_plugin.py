"""Technology fingerprinting.

Matches declarative fingerprints (rules/technology/*.yaml) against the
snapshot. Adding a technology is a YAML change; this file never grows.

Publishes a `technologies` artifact that the CMS plugin depends on — declared
via meta.depends_on there, never imported from here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import Confidence, Severity, TechCategory, TechnologyId
from leadkhojo.core.utils.clock import iso
from leadkhojo.core.utils.versions import is_outdated, major_versions_behind
from leadkhojo.plugins.base import BasePlugin, PluginContext, PluginKind, PluginMeta, PluginResult
from leadkhojo.plugins.rules import Fingerprint, RulePacks, Signal

PLUGIN_ID = "technologies"
CATEGORY = "technology"

_GENERATOR_RE = re.compile(
    r"""<meta[^>]+name\s*=\s*["']generator["'][^>]+content\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DetectedTechnology:
    id: TechnologyId
    name: str
    category: TechCategory
    version: str | None
    confidence: Confidence
    evidence: dict[str, Any]
    is_outdated: bool | None = None
    versions_behind: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "category": self.category.value,
            "version": self.version,
            "confidence": self.confidence.value,
            "evidence": self.evidence,
            "is_outdated": self.is_outdated,
            "versions_behind": self.versions_behind,
        }


class TechnologiesPlugin(BasePlugin):
    meta: ClassVar[PluginMeta] = PluginMeta(
        id=PLUGIN_ID,
        name="Technology Detection",
        version="1.0.0",
        kind=PluginKind.ANALYZER,
        description="Fingerprints CMS, frameworks, servers, CDN, analytics and more.",
        provides=("technologies", "by_category", "has_analytics", "has_cdn", "has_waf"),
        budget_ms=1500,
    )

    def __init__(self, packs: RulePacks) -> None:
        self._packs = packs

    def run(self, ctx: PluginContext) -> PluginResult:
        snap = ctx.snapshot
        if not snap.pages:
            return self._result(
                (
                    Finding.not_applicable(
                        "TECH-01",
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        reason="No pages were captured",
                    ),
                ),
                {"technologies": [], "by_category": {}},
            )

        html_blob = "\n".join(snap.html_documents())
        headers = {k.lower(): v for k, v in snap.all_headers().items()}
        cookie_names = [c.name for c in snap.cookies]
        urls = [p.final_url for p in snap.pages]

        detected: list[DetectedTechnology] = []
        for fingerprint in self._packs.fingerprints:
            hit = self._match(fingerprint, html_blob, headers, cookie_names, urls)
            if hit is not None:
                detected.append(hit)

        detected.sort(key=lambda t: (t.category.value, str(t.id)))

        by_category: dict[str, list[dict[str, Any]]] = {}
        for tech in detected:
            by_category.setdefault(tech.category.value, []).append(tech.to_dict())

        findings: list[Finding] = [
            Finding.informational(
                "TECH-01",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title=f"{len(detected)} technologies detected",
                evidence={
                    "count": len(detected),
                    "technologies": [t.name for t in detected][:25],
                },
            )
        ]

        # An outdated library with a *known* version is a real, specific finding.
        for tech in detected:
            if tech.is_outdated and tech.version:
                findings.append(self._outdated_finding(ctx, tech))

        return self._result(
            tuple(findings),
            {
                "technologies": [t.to_dict() for t in detected],
                "by_category": by_category,
                # Booleans the opportunity rules condition on directly.
                "has_analytics": any(t.category is TechCategory.ANALYTICS for t in detected),
                "has_cdn": any(t.category is TechCategory.CDN for t in detected),
                "has_waf": any(t.category is TechCategory.WAF for t in detected),
            },
        )

    # -- matching ----------------------------------------------------------

    def _match(
        self,
        fingerprint: Fingerprint,
        html: str,
        headers: dict[str, str],
        cookies: list[str],
        urls: list[str],
    ) -> DetectedTechnology | None:
        best: Confidence | None = None
        version: str | None = None
        evidence: dict[str, Any] = {}

        for signal in fingerprint.signals:
            match_value = self._evaluate(signal, html, headers, cookies, urls)
            if match_value is None:
                continue

            matched_text, captured_version = match_value
            evidence[signal.type] = matched_text[:200]
            if captured_version and not version:
                version = captured_version
            if best is None or signal.confidence.weight > best.weight:
                best = signal.confidence

        if best is None:
            return None

        latest = fingerprint.latest_version
        outdated = is_outdated(version, latest)
        behind = major_versions_behind(version, latest)

        return DetectedTechnology(
            id=fingerprint.id,
            name=fingerprint.name,
            category=fingerprint.category,
            version=version,
            confidence=best,
            evidence=evidence,
            is_outdated=outdated,
            versions_behind=behind,
        )

    def _evaluate(
        self,
        signal: Signal,
        html: str,
        headers: dict[str, str],
        cookies: list[str],
        urls: list[str],
    ) -> tuple[str, str | None] | None:
        regex = signal.regex

        if signal.type == "header":
            value = headers.get((signal.name or "").lower())
            if value is None:
                return None
            match = regex.search(value)
            if not match:
                return None
            return f"{signal.name}: {value}", self._version_from(match, signal)

        if signal.type == "cookie":
            for name in cookies:
                if regex.search(name):
                    return f"cookie {name}", None
            return None

        if signal.type == "meta_generator":
            meta = _GENERATOR_RE.search(html)
            if not meta:
                return None
            content = meta.group(1)
            match = regex.search(content)
            if not match:
                return None
            return f"generator: {content}", self._version_from(match, signal)

        if signal.type in ("html", "script_src"):
            match = regex.search(html)
            if not match:
                return None
            return match.group(0), self._version_from(match, signal)

        if signal.type == "url":
            for url in urls:
                match = regex.search(url)
                if match:
                    return url, self._version_from(match, signal)
            return None

        return None

    @staticmethod
    def _version_from(match: re.Match[str], signal: Signal) -> str | None:
        """Pull the version out of a capture group, if the rule declares one.

        A rule can name a group the pattern does not have — that is a rule bug,
        not a crash. Detection without a version is still a valid result.
        """
        if signal.version_group is None:
            return None
        try:
            captured = match.group(signal.version_group)
        except (IndexError, re.error):
            return None
        if not captured:
            return None
        return str(captured).strip() or None

    def _outdated_finding(self, ctx: PluginContext, tech: DetectedTechnology) -> Finding:
        latest = self._packs.latest_versions.get(str(tech.id))
        behind_text = (
            f" — {tech.versions_behind} major release(s) behind" if tech.versions_behind else ""
        )
        return Finding.failed(
            f"TECH-OUTDATED-{str(tech.id).upper()}",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            severity=Severity.MEDIUM if (tech.versions_behind or 0) < 2 else Severity.HIGH,
            title=f"{tech.name} {tech.version} is outdated",
            description=(
                f"The site runs {tech.name} {tech.version}{behind_text}. "
                f"The current release is {latest}. Older releases stop receiving "
                "security fixes."
            ),
            evidence={
                "technology": tech.name,
                "detected_version": tech.version,
                "latest_version": latest,
                "versions_behind": tech.versions_behind,
                "detection": tech.evidence,
                "checked_at": iso(ctx.now),
            },
            remediation=f"Upgrade {tech.name} to {latest} and establish a patching schedule.",
        )


__all__ = ["PLUGIN_ID", "DetectedTechnology", "TechnologiesPlugin"]
