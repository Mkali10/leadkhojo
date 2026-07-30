"""The ONLY place an AI model may ever touch an opportunity.

The contract is deliberately narrow:

    rewrite(opportunity) -> str

A rewriter receives a completed, deterministic Opportunity and returns prose.
It cannot create an opportunity, suppress one, change its urgency, or add a
fact — the return type makes that structurally impossible.

Two further guards:

  * `evidence` is never passed to a rewriter. Facts cannot be laundered
    through prose.
  * a rewrite introducing a number absent from the deterministic text is
    rejected. This catches the failure that actually matters: a hallucinated
    date or count landing in an email a user sends to a prospect.

v1 ships NullRewriter. No model is called.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol, runtime_checkable

from leadkhojo.opportunities.schemas import Opportunity

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


@runtime_checkable
class OpportunityRewriter(Protocol):
    """Rephrases existing text. Cannot produce facts."""

    def rewrite(self, opportunity: Opportunity) -> str: ...


class NullRewriter:
    """The default and the only implementation in v1. Returns the input text."""

    def rewrite(self, opportunity: Opportunity) -> str:
        return opportunity.description


def extract_numbers(text: str) -> set[str]:
    return {m.group().replace(",", "") for m in _NUMBER_RE.finditer(text)}


def rewrite_is_safe(original: str, rewritten: str) -> tuple[bool, str | None]:
    """Reject a rewrite that invents a numeric claim.

    Every number in the rewrite must already appear in the deterministic text.
    Dropping numbers is fine (a rewrite may be shorter); inventing one is not.
    """
    if not rewritten.strip():
        return False, "empty rewrite"

    invented = extract_numbers(rewritten) - extract_numbers(original)
    if invented:
        return False, f"introduced numbers absent from the evidence: {sorted(invented)}"

    return True, None


def apply_rewriter(
    opportunity: Opportunity,
    rewriter: OpportunityRewriter | None,
) -> Opportunity:
    """Attach a rewrite if one is available, safe, and different.

    Any failure — exception, unsafe output, no rewriter — leaves the
    deterministic opportunity untouched. AI is never on the critical path.
    """
    if rewriter is None or isinstance(rewriter, NullRewriter):
        return opportunity

    try:
        candidate = rewriter.rewrite(opportunity)
    except Exception as exc:
        logger.warning(
            "rewriter.failed",
            extra={"rule_id": opportunity.rule_id, "error": f"{type(exc).__name__}: {exc}"},
        )
        return opportunity

    safe, reason = rewrite_is_safe(opportunity.description, candidate)
    if not safe:
        logger.warning(
            "rewriter.rejected",
            extra={"rule_id": opportunity.rule_id, "reason": reason},
        )
        return opportunity

    if candidate.strip() == opportunity.description.strip():
        return opportunity

    return opportunity.with_rewrite(candidate.strip())
