"""Finding — the shared currency of every plugin.

A Finding is an observation about a website at a moment in time. It is frozen
because it is a fact about the past: nothing downstream may edit one.

Evidence is mandatory. A finding without evidence is not shippable — the user
must be able to verify the claim themselves, and to paste it into an email.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from leadkhojo.core.types import CheckId, FindingStatus, PluginId, Severity


@dataclass(frozen=True, slots=True)
class Finding:
    check_id: CheckId
    plugin_id: PluginId
    category: str
    status: FindingStatus
    severity: Severity
    title: str
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    remediation: str | None = None

    def __post_init__(self) -> None:
        # A problem must carry evidence. Passes and N/A may be evidence-light,
        # but anything we would put in front of a prospect must be provable.
        if self.status.is_problem and not self.evidence:
            raise ValueError(f"{self.check_id}: a {self.status.value} finding must carry evidence")

    @property
    def is_problem(self) -> bool:
        return self.status.is_problem

    # -- constructors ------------------------------------------------------
    # Named constructors keep plugin code readable and make the status/severity
    # pairing hard to get wrong (a PASS with CRITICAL severity is nonsense).

    @classmethod
    def failed(
        cls,
        check_id: str,
        *,
        plugin_id: str,
        category: str,
        severity: Severity,
        title: str,
        description: str,
        evidence: dict[str, Any],
        remediation: str | None = None,
    ) -> Finding:
        return cls(
            check_id=CheckId(check_id),
            plugin_id=PluginId(plugin_id),
            category=category,
            status=FindingStatus.FAIL,
            severity=severity,
            title=title,
            description=description,
            evidence=evidence,
            remediation=remediation,
        )

    @classmethod
    def warned(
        cls,
        check_id: str,
        *,
        plugin_id: str,
        category: str,
        title: str,
        description: str,
        evidence: dict[str, Any],
        severity: Severity = Severity.LOW,
        remediation: str | None = None,
    ) -> Finding:
        return cls(
            check_id=CheckId(check_id),
            plugin_id=PluginId(plugin_id),
            category=category,
            status=FindingStatus.WARN,
            severity=severity,
            title=title,
            description=description,
            evidence=evidence,
            remediation=remediation,
        )

    @classmethod
    def passed(
        cls,
        check_id: str,
        *,
        plugin_id: str,
        category: str,
        title: str,
        description: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> Finding:
        return cls(
            check_id=CheckId(check_id),
            plugin_id=PluginId(plugin_id),
            category=category,
            status=FindingStatus.PASS,
            severity=Severity.INFO,
            title=title,
            description=description,
            evidence=evidence or {},
        )

    @classmethod
    def informational(
        cls,
        check_id: str,
        *,
        plugin_id: str,
        category: str,
        title: str,
        description: str = "",
        evidence: dict[str, Any] | None = None,
    ) -> Finding:
        return cls(
            check_id=CheckId(check_id),
            plugin_id=PluginId(plugin_id),
            category=category,
            status=FindingStatus.INFO,
            severity=Severity.INFO,
            title=title,
            description=description,
            evidence=evidence or {},
        )

    @classmethod
    def not_applicable(
        cls,
        check_id: str,
        *,
        plugin_id: str,
        category: str,
        reason: str,
    ) -> Finding:
        """We could not evaluate this check.

        This is not a failure. Reporting FAIL when we simply could not look is
        how a tool starts making false accusations.
        """
        return cls(
            check_id=CheckId(check_id),
            plugin_id=PluginId(plugin_id),
            category=category,
            status=FindingStatus.NOT_APPLICABLE,
            severity=Severity.INFO,
            title="Not applicable",
            description=reason,
            evidence={"reason": reason},
        )


def sort_findings(findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
    """Deterministic ordering: problems first, worst first, then by check id."""
    return tuple(
        sorted(
            findings,
            key=lambda f: (not f.is_problem, f.severity.rank, f.check_id),
        )
    )


def evidence_timestamp(now: datetime) -> str:
    """Every piece of evidence records when we looked."""
    return now.isoformat().replace("+00:00", "Z")
