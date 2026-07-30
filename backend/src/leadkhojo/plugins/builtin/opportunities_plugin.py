"""Opportunities plugin — the SYNTHESIZER.

Depends on every analyzer. Converts their findings into sellable work by
delegating to the deterministic OpportunityEngine.

Note the shape of the AI seam here: the rewriter is injected, defaults to
NullRewriter, and is applied AFTER the engine has already produced complete
opportunities. It receives an Opportunity and returns a string. It cannot
create, suppress, reorder, or re-rank anything.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from leadkhojo.core.findings import Finding
from leadkhojo.opportunities.engine import OpportunityEngine
from leadkhojo.opportunities.rewriter import (
    NullRewriter,
    OpportunityRewriter,
    apply_rewriter,
)
from leadkhojo.opportunities.schemas import Opportunity
from leadkhojo.plugins.base import BasePlugin, PluginContext, PluginKind, PluginMeta, PluginResult

PLUGIN_ID = "opportunities"
CATEGORY = "opportunities"


class OpportunitiesPlugin(BasePlugin):
    meta: ClassVar[PluginMeta] = PluginMeta(
        id=PLUGIN_ID,
        name="Opportunity Engine",
        version="1.0.0",
        kind=PluginKind.SYNTHESIZER,
        description="Converts findings into concrete, evidence-backed sales opportunities.",
        depends_on=("ssl", "dns", "headers", "technologies", "cms", "performance", "contacts"),
        provides=("opportunities", "opportunity_count"),
        budget_ms=100,
    )

    def __init__(
        self,
        engine: OpportunityEngine,
        rewriter: OpportunityRewriter | None = None,
    ) -> None:
        self._engine = engine
        # Default is the identity rewriter: v1 makes no model call at all.
        self._rewriter = rewriter or NullRewriter()

    def run(self, ctx: PluginContext) -> PluginResult:
        findings = ctx.all_findings()
        artifacts = ctx.all_artifacts()

        opportunities = self._engine.generate(
            findings,
            artifacts,
            now=ctx.now,
            domain=str(ctx.snapshot.domain),
        )

        # Presentation layer only. Cannot alter a single fact.
        opportunities = tuple(apply_rewriter(o, self._rewriter) for o in opportunities)

        summary = Finding.informational(
            "OPP-01",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title=f"{len(opportunities)} opportunities identified",
            evidence={
                "count": len(opportunities),
                "by_urgency": _count_by(opportunities, lambda o: o.urgency.value),
                "by_category": _count_by(opportunities, lambda o: o.category.value),
                "top": [o.title for o in opportunities[:5]],
            },
        )

        return self._result(
            findings=(summary,),
            artifacts={
                "opportunities": [
                    {
                        "rule_id": str(o.rule_id),
                        "title": o.title,
                        "category": o.category.value,
                        "urgency": o.urgency.value,
                        "description": o.description,
                        "description_ai": o.description_ai,
                        "pitch_angle": o.pitch_angle,
                        "evidence": o.evidence,
                        "triggered_by": list(o.triggered_by),
                    }
                    for o in opportunities
                ],
                "opportunity_count": len(opportunities),
            },
            opportunities=opportunities,
        )


def _count_by(
    items: tuple[Opportunity, ...],
    key: Callable[[Opportunity], str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = key(item)
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


__all__ = ["PLUGIN_ID", "OpportunitiesPlugin"]
