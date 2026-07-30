"""Opportunity — a finding converted into something you can sell.

`description` is produced deterministically by the rule engine and is the
authoritative text. `description_ai` is an OPTIONAL rephrasing and never
replaces it. Both are retained; the deterministic one is always retrievable.

See docs/03-ARCHITECTURE.md section 9.3 for the AI boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from leadkhojo.core.types import OpportunityCategory, RuleId, Urgency


@dataclass(frozen=True, slots=True)
class Opportunity:
    rule_id: RuleId
    title: str
    category: OpportunityCategory
    urgency: Urgency
    description: str
    """Deterministic. Produced by the rule engine. The source of truth."""

    pitch_angle: str
    evidence: dict[str, Any] = field(default_factory=dict)
    triggered_by: tuple[str, ...] = ()

    description_ai: str | None = None
    """Optional AI rephrasing of `description`. Adds no facts. May be dropped
    entirely without changing anything true about this opportunity."""

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError(f"{self.rule_id}: an opportunity must carry evidence")
        if not self.triggered_by:
            raise ValueError(f"{self.rule_id}: an opportunity must name what triggered it")

    @property
    def display_description(self) -> str:
        """What the UI shows. Falls back to the deterministic text always."""
        return self.description_ai or self.description

    def with_rewrite(self, text: str) -> Opportunity:
        """Attach an AI rephrasing.

        Note what this cannot do: it cannot change the title, urgency,
        category, evidence, or `description`. A rewriter returns a string, so
        it is structurally incapable of altering a fact.
        """
        from dataclasses import replace

        return replace(self, description_ai=text)


def sort_opportunities(items: tuple[Opportunity, ...]) -> tuple[Opportunity, ...]:
    """Deterministic ordering: most urgent first, then alphabetical by rule id."""
    return tuple(sorted(items, key=lambda o: (o.urgency.rank, o.rule_id)))
