"""Deterministic Opportunity Engine.

    Rules ──▶ Evidence ──▶ Opportunity ──▶ (optional AI rewrite)
    └──────── deterministic core ────────┘

Same snapshot + same clock + same rules => byte-identical opportunities. No
model is consulted to decide whether an opportunity exists, what it says, how
urgent it is, or what evidence backs it.

THE SPECIFICITY GATE
--------------------
A rule whose template cannot be filled with concrete values produces NOTHING.
"Your CMS might be outdated" is worse than silence: it wastes the user's
attention and teaches them to distrust every other row.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from string import Template
from typing import Any

import yaml

from leadkhojo.core.errors import RuleLoadError
from leadkhojo.core.findings import Finding
from leadkhojo.core.types import FindingStatus, OpportunityCategory, RuleId, Urgency
from leadkhojo.opportunities.schemas import Opportunity, sort_opportunities

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\$\{(\w+)\}|\$(\w+)")


@dataclass(frozen=True, slots=True)
class Condition:
    """One requirement a rule places on the analysis output."""

    # finding_failed | finding_passed | finding_absent
    # artifact_truthy | artifact_falsy | artifact_equals
    kind: str
    check_id: str | None = None
    plugin: str | None = None
    key: str | None = None
    value: Any = None

    def matches(
        self,
        findings_by_id: Mapping[str, Finding],
        artifacts: Mapping[str, Mapping[str, Any]],
    ) -> bool:
        if self.kind == "finding_failed":
            f = findings_by_id.get(self.check_id or "")
            return f is not None and f.status in (FindingStatus.FAIL, FindingStatus.WARN)

        if self.kind == "finding_passed":
            f = findings_by_id.get(self.check_id or "")
            return f is not None and f.status is FindingStatus.PASS

        if self.kind == "finding_absent":
            f = findings_by_id.get(self.check_id or "")
            return f is None or f.status is FindingStatus.NOT_APPLICABLE

        # An artifact a plugin did not publish means that plugin could not
        # evaluate — no pages captured, a failed crawl, a skipped dependency.
        # It does NOT mean False. Treating a missing key as falsy generated
        # "No website analytics installed" for a site that timed out and was
        # never fetched, which is a claim we have no basis for.
        if self.kind in ("artifact_truthy", "artifact_falsy", "artifact_equals"):
            published = artifacts.get(self.plugin or "", {})
            if (self.key or "") not in published:
                return False
            value = published.get(self.key or "")

            if self.kind == "artifact_truthy":
                return bool(value)
            if self.kind == "artifact_falsy":
                return not value
            return value == self.value

        logger.warning("opportunity.unknown_condition", extra={"kind": self.kind})
        return False


@dataclass(frozen=True, slots=True)
class OpportunityRule:
    id: RuleId
    title: str
    category: OpportunityCategory
    urgency: Urgency
    requires: tuple[Condition, ...]
    description_template: str
    pitch_angle: str
    evidence_from: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()


class OpportunityEngine:
    """Turns findings into sellable work. Deterministic, always."""

    def __init__(self, rules: Sequence[OpportunityRule]) -> None:
        # Sorted so evaluation order — and therefore output order — is stable.
        self._rules = tuple(sorted(rules, key=lambda r: r.id))

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(str(r.id) for r in self._rules)

    def generate(
        self,
        findings: Sequence[Finding],
        artifacts: Mapping[str, Mapping[str, Any]],
        *,
        now: datetime,
        domain: str = "",
    ) -> tuple[Opportunity, ...]:
        findings_by_id = {str(f.check_id): f for f in findings}

        produced: list[Opportunity] = []
        for rule in self._rules:
            if not all(c.matches(findings_by_id, artifacts) for c in rule.requires):
                continue

            evidence = self._collect_evidence(rule, findings_by_id, artifacts, domain, now)
            values = self._template_values(evidence, domain)

            description = self._render(rule.description_template, values)
            if description is None:
                # SPECIFICITY GATE: a placeholder had no concrete value.
                logger.debug(
                    "opportunity.suppressed_unspecific",
                    extra={"rule_id": str(rule.id), "reason": "unfilled placeholder"},
                )
                continue

            title = self._render(rule.title, values) or rule.title

            produced.append(
                Opportunity(
                    rule_id=rule.id,
                    title=title,
                    category=rule.category,
                    urgency=rule.urgency,
                    description=description,
                    pitch_angle=rule.pitch_angle,
                    evidence=evidence,
                    triggered_by=tuple(sorted(rule.evidence_from)) or (str(rule.id),),
                )
            )

        return sort_opportunities(tuple(self._drop_superseded(produced)))

    # -- internals ---------------------------------------------------------

    def _drop_superseded(self, items: list[Opportunity]) -> list[Opportunity]:
        """Merge overlapping opportunities into the strongest single one.

        A site with an *expired* certificate should not also be told its
        certificate is *expiring*.
        """
        by_id = {str(o.rule_id): o for o in items}
        rules_by_id = {str(r.id): r for r in self._rules}
        drop: set[str] = set()
        for opp in items:
            rule = rules_by_id.get(str(opp.rule_id))
            if rule:
                drop.update(s for s in rule.supersedes if s in by_id)
        return [o for o in items if str(o.rule_id) not in drop]

    @staticmethod
    def _collect_evidence(
        rule: OpportunityRule,
        findings_by_id: Mapping[str, Finding],
        artifacts: Mapping[str, Mapping[str, Any]],
        domain: str,
        now: datetime,
    ) -> dict[str, Any]:
        from leadkhojo.core.utils.clock import iso

        evidence: dict[str, Any] = {"domain": domain, "generated_at": iso(now)}
        for check_id in rule.evidence_from:
            finding = findings_by_id.get(check_id)
            if finding is not None:
                evidence[check_id] = dict(finding.evidence)
        # Selected artifacts referenced by conditions are useful context.
        for condition in rule.requires:
            if condition.plugin and condition.key:
                value = artifacts.get(condition.plugin, {}).get(condition.key)
                if value is not None and not isinstance(value, (list, dict)):
                    evidence[f"{condition.plugin}.{condition.key}"] = value
        return evidence

    @staticmethod
    def _template_values(evidence: Mapping[str, Any], domain: str) -> dict[str, Any]:
        """Flatten evidence into template variables.

        `TLS-04.days_remaining` becomes `days_remaining`. Later checks do not
        clobber earlier ones, so the first (highest-priority) source wins.
        """
        values: dict[str, Any] = {"domain": domain}
        for key, blob in evidence.items():
            if isinstance(blob, dict):
                for inner_key, inner_value in blob.items():
                    if inner_value is None or isinstance(inner_value, (list, dict)):
                        continue
                    values.setdefault(inner_key, inner_value)
            elif blob is not None:
                values.setdefault(key.replace(".", "_"), blob)
        return values

    @staticmethod
    def _render(template: str, values: Mapping[str, Any]) -> str | None:
        """Fill a template, or return None if any placeholder is unavailable.

        Returning None is the specificity gate firing. It is not an error path
        — it is the engine correctly declining to say something vague.
        """
        required = {m.group(1) or m.group(2) for m in _PLACEHOLDER_RE.finditer(template)}
        missing = [name for name in required if values.get(name) in (None, "")]
        if missing:
            return None
        try:
            rendered = Template(template).substitute(values)
        except (KeyError, ValueError):
            return None
        return " ".join(rendered.split())


# -- rule loading ----------------------------------------------------------


def _parse_condition(raw: dict[str, Any], rule_id: str) -> Condition:
    kind = raw.get("kind")
    valid = {
        "finding_failed",
        "finding_passed",
        "finding_absent",
        "artifact_truthy",
        "artifact_falsy",
        "artifact_equals",
    }
    if kind not in valid:
        raise RuleLoadError(f"{rule_id}: unknown condition kind {kind!r}")
    return Condition(
        kind=kind,
        check_id=raw.get("check_id"),
        plugin=raw.get("plugin"),
        key=raw.get("key"),
        value=raw.get("value"),
    )


def load_opportunity_rules(rules_dir: Any) -> tuple[OpportunityRule, ...]:
    from pathlib import Path

    directory = Path(rules_dir) / "opportunities"
    if not directory.is_dir():
        raise RuleLoadError(f"Opportunity rules directory not found: {directory}")

    rules: list[OpportunityRule] = []
    seen: set[str] = set()

    for path in sorted(directory.glob("*.yaml")):
        try:
            entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        except yaml.YAMLError as exc:
            raise RuleLoadError(f"{path.name}: invalid YAML: {exc}") from exc
        if not isinstance(entries, list):
            raise RuleLoadError(f"{path.name}: expected a list of rules")

        for entry in entries:
            rule_id = entry.get("id")
            if not rule_id:
                raise RuleLoadError(f"{path.name}: a rule is missing 'id'")
            if rule_id in seen:
                raise RuleLoadError(f"Duplicate opportunity rule id: {rule_id!r}")
            seen.add(rule_id)

            try:
                category = OpportunityCategory(entry["category"])
                urgency = Urgency(entry["urgency"])
            except (KeyError, ValueError) as exc:
                raise RuleLoadError(f"{rule_id}: bad category/urgency: {exc}") from exc

            for field_name in ("title", "description_template", "pitch_angle"):
                if not entry.get(field_name):
                    raise RuleLoadError(f"{rule_id}: missing required field {field_name!r}")

            rules.append(
                OpportunityRule(
                    id=RuleId(rule_id),
                    title=entry["title"],
                    category=category,
                    urgency=urgency,
                    requires=tuple(
                        _parse_condition(c, rule_id) for c in (entry.get("requires") or [])
                    ),
                    description_template=entry["description_template"],
                    pitch_angle=entry["pitch_angle"],
                    evidence_from=tuple(entry.get("evidence_from") or ()),
                    supersedes=tuple(entry.get("supersedes") or ()),
                )
            )

    if not rules:
        raise RuleLoadError(f"No opportunity rules loaded from {directory}")
    return tuple(rules)


__all__ = [
    "Condition",
    "OpportunityEngine",
    "OpportunityRule",
    "load_opportunity_rules",
]
