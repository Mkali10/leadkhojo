"""Four independent scores.

They are independent by design. A security firm sorts by Opportunity Score;
a design agency sorts by Website Quality ascending (worst first); a
generalist sorts by Lead Quality. One blended number would serve none of them.

Every score exposes its component breakdown — a score without a breakdown is
not shippable, because the user cannot act on a number they cannot explain.

Missing input lowers `confidence`; it never silently zeroes a component. A
site we could not check is not a site that failed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import FindingStatus, Severity
from leadkhojo.opportunities.schemas import Opportunity


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    total: int
    components: dict[str, float] = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "components": {k: round(v, 1) for k, v in self.components.items()},
            "confidence": round(self.confidence, 2),
        }


@dataclass(frozen=True, slots=True)
class Scores:
    lead: ScoreBreakdown
    website: ScoreBreakdown
    security: ScoreBreakdown
    opportunity: ScoreBreakdown

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead": self.lead.to_dict(),
            "website": self.website.to_dict(),
            "security": self.security.to_dict(),
            "opportunity": self.opportunity.to_dict(),
        }


def _clamp(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _by_id(findings: Sequence[Finding]) -> dict[str, Finding]:
    return {str(f.check_id): f for f in findings}


def _failed(findings: dict[str, Finding], check_id: str) -> bool:
    f = findings.get(check_id)
    return f is not None and f.status in (FindingStatus.FAIL, FindingStatus.WARN)


def _evaluated(findings: dict[str, Finding], check_ids: Sequence[str]) -> float:
    """Fraction of checks we were actually able to evaluate."""
    if not check_ids:
        return 1.0
    known = sum(
        1
        for cid in check_ids
        if (f := findings.get(cid)) is not None and f.status is not FindingStatus.NOT_APPLICABLE
    )
    return known / len(check_ids)


# ---------------------------------------------------------------- security

_SECURITY_GROUPS: dict[str, tuple[float, tuple[str, ...]]] = {
    "tls": (35.0, ("TLS-01", "TLS-02", "TLS-03", "TLS-04", "TLS-05", "TLS-06", "TLS-08")),
    "headers": (25.0, ("HDR-01", "HDR-02", "HDR-03", "HDR-04", "HDR-05", "HDR-06")),
    "email_auth": (25.0, ("DNS-01", "DNS-02", "DNS-03", "DNS-04")),
    "disclosure": (15.0, ("HDR-07", "CNT-01", "CNT-02", "CKY-01", "CKY-02")),
}


def score_security(findings: Sequence[Finding]) -> ScoreBreakdown:
    by_id = _by_id(findings)
    components: dict[str, float] = {}
    all_checks: list[str] = []

    for group, (weight, checks) in _SECURITY_GROUPS.items():
        all_checks.extend(checks)
        evaluable = [
            c
            for c in checks
            if (f := by_id.get(c)) and f.status is not FindingStatus.NOT_APPLICABLE
        ]
        if not evaluable:
            # Nothing to judge: award the full weight rather than punish a
            # site for something we could not measure. Confidence carries it.
            components[group] = weight
            continue
        failures = sum(1 for c in evaluable if _failed(by_id, c))
        components[group] = weight * (1 - failures / len(evaluable))

    # Critical findings cut through the group averages.
    critical = sum(
        1 for f in findings if f.status is FindingStatus.FAIL and f.severity is Severity.CRITICAL
    )
    penalty = min(40.0, critical * 20.0)
    if critical:
        components["critical_penalty"] = -penalty

    total = sum(components.values())
    return ScoreBreakdown(
        total=_clamp(total),
        components=components,
        confidence=_evaluated(by_id, all_checks),
    )


# ---------------------------------------------------------------- website


def score_website(
    findings: Sequence[Finding],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> ScoreBreakdown:
    by_id = _by_id(findings)
    components: dict[str, float] = {}
    checks = ("PERF-01", "PERF-02", "PERF-03", "PERF-04", "TLS-01", "CMS-02")

    components["performance"] = 30.0 if not _failed(by_id, "PERF-01") else 8.0
    components["mobile"] = 20.0 if not _failed(by_id, "PERF-04") else 0.0
    components["delivery"] = 15.0 if not _failed(by_id, "PERF-03") else 6.0
    components["secure_transport"] = 15.0 if not _failed(by_id, "TLS-01") else 0.0

    # Modernity: an outdated CMS is a real signal; an unknown version is not.
    cms = artifacts.get("cms", {}).get("cms")
    if isinstance(cms, dict) and cms.get("is_outdated") is True:
        components["modernity"] = 4.0
    elif isinstance(cms, dict) and cms.get("is_outdated") is False:
        components["modernity"] = 20.0
    else:
        components["modernity"] = 14.0  # unknown: neutral, not punitive

    return ScoreBreakdown(
        total=_clamp(sum(components.values())),
        components=components,
        confidence=_evaluated(by_id, checks),
    )


# ---------------------------------------------------------------- lead


def score_lead(
    findings: Sequence[Finding],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> ScoreBreakdown:
    contacts = artifacts.get("contacts", {})
    contact_list: list[dict[str, Any]] = contacts.get("contacts", []) or []
    kinds = {c.get("kind") for c in contact_list}

    components: dict[str, float] = {}

    # Contactability (40) — can you actually reach them?
    contactability = 0.0
    if contacts.get("primary_email"):
        contactability += 22.0
    if contacts.get("primary_phone"):
        contactability += 10.0
    if "form" in kinds:
        contactability += 5.0
    if "address" in kinds:
        contactability += 3.0
    components["contactability"] = min(40.0, contactability)

    # Business signals (25) — do they look like a real operating business?
    signals = 0.0
    social_count = sum(1 for c in contact_list if c.get("kind") == "social")
    signals += min(12.0, social_count * 4.0)
    tech_count = len(artifacts.get("technologies", {}).get("technologies", []) or [])
    signals += min(13.0, tech_count * 1.5)
    components["business_signals"] = signals

    # Reachable and real (20)
    by_id = _by_id(findings)
    reachable = 20.0
    if _failed(by_id, "TLS-01"):
        reachable -= 5.0
    components["site_reachable"] = max(0.0, reachable)

    # Engagement surface (15) — is there anything to talk about?
    opportunity_count = artifacts.get("opportunities", {}).get("opportunity_count", 0) or 0
    components["engagement_surface"] = min(15.0, float(opportunity_count) * 3.0)

    confidence = 1.0 if contact_list else 0.7

    return ScoreBreakdown(
        total=_clamp(sum(components.values())),
        components=components,
        confidence=confidence,
    )


# ---------------------------------------------------------------- opportunity


def score_opportunity(
    opportunities: Sequence[Opportunity],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> ScoreBreakdown:
    """How much is there to sell here?

    Weighted by urgency, then scaled by contactability — an unreachable
    prospect is worth nothing regardless of how broken their site is.
    """
    components: dict[str, float] = {}

    raw = sum(o.urgency.weight for o in opportunities)
    components["opportunity_value"] = min(70.0, raw)

    critical = sum(1 for o in opportunities if o.urgency.value == "critical")
    components["urgency_bonus"] = min(15.0, critical * 7.5)

    contacts = artifacts.get("contacts", {})
    if contacts.get("primary_email"):
        components["reachable"] = 15.0
    elif contacts.get("primary_phone"):
        components["reachable"] = 9.0
    else:
        # Nothing to sell if you cannot start a conversation.
        components["reachable"] = 0.0

    total = sum(components.values())
    if components["reachable"] == 0.0:
        total *= 0.5

    return ScoreBreakdown(
        total=_clamp(total),
        components=components,
        confidence=1.0,
    )


def compute_scores(
    findings: Sequence[Finding],
    opportunities: Sequence[Opportunity],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> Scores:
    return Scores(
        lead=score_lead(findings, artifacts),
        website=score_website(findings, artifacts),
        security=score_security(findings),
        opportunity=score_opportunity(opportunities, artifacts),
    )


__all__ = ["ScoreBreakdown", "Scores", "compute_scores"]
