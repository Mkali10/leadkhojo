"""Opportunity Engine tests.

    Rule -> Evidence -> Finding -> Opportunity -> Recommendation

Deterministic by construction. No model decides whether an opportunity
exists, what it says, how urgent it is, or what evidence backs it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from leadkhojo.core.errors import RuleLoadError
from leadkhojo.core.findings import Finding
from leadkhojo.core.types import (
    CheckId,
    FindingStatus,
    OpportunityCategory,
    PluginId,
    RuleId,
    Severity,
    Urgency,
)
from leadkhojo.opportunities.engine import OpportunityEngine, load_opportunity_rules
from leadkhojo.opportunities.rewriter import NullRewriter, apply_rewriter, rewrite_is_safe
from leadkhojo.opportunities.schemas import Opportunity

REPO_RULES = Path(__file__).resolve().parents[3] / "rules"


@pytest.fixture(scope="module")
def engine() -> OpportunityEngine:
    return OpportunityEngine(load_opportunity_rules(REPO_RULES))


def _finding(check_id: str, evidence: dict, status: FindingStatus = FindingStatus.FAIL) -> Finding:
    return Finding(
        check_id=CheckId(check_id),
        plugin_id=PluginId("test"),
        category="test",
        status=status,
        severity=Severity.HIGH,
        title=check_id,
        description="",
        evidence=evidence,
    )


EXPIRING = _finding("TLS-04", {"not_after": "2026-08-08T00:00:00Z", "days_remaining": 9})
NO_DMARC = _finding("DNS-03", {"query": "_dmarc.acme.com TXT", "result": "NXDOMAIN"})


# ---------------------------------------------------------------- rule loading


def test_the_shipped_rules_load_and_validate() -> None:
    rules = load_opportunity_rules(REPO_RULES)
    assert len(rules) >= 15

    ids = [str(r.id) for r in rules]
    assert len(ids) == len(set(ids)), "rule ids must be unique"


def test_every_rule_has_the_fields_a_salesperson_needs() -> None:
    for rule in load_opportunity_rules(REPO_RULES):
        assert rule.title
        assert rule.description_template
        assert rule.pitch_angle, f"{rule.id} has no pitch angle"


def test_a_rule_missing_a_required_field_fails_at_startup(tmp_path: Path) -> None:
    directory = tmp_path / "opportunities"
    directory.mkdir()
    (directory / "bad.yaml").write_text(
        "- id: x\n  category: security\n  urgency: high\n  title: T\n", encoding="utf-8"
    )
    with pytest.raises(RuleLoadError, match="description_template"):
        load_opportunity_rules(tmp_path)


def test_an_unknown_condition_kind_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "opportunities"
    directory.mkdir()
    (directory / "bad.yaml").write_text(
        "- id: x\n  category: security\n  urgency: high\n  title: T\n"
        "  description_template: D\n  pitch_angle: P\n"
        "  requires:\n    - {kind: telepathy}\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleLoadError, match="unknown condition kind"):
        load_opportunity_rules(tmp_path)


# ---------------------------------------------------------------- determinism


def test_output_is_byte_identical_across_50_runs(engine: OpportunityEngine, now: datetime) -> None:
    """FR-OPP-8. Deterministic is a property, not an intention."""
    runs = [
        engine.generate((EXPIRING, NO_DMARC), {}, now=now, domain="acme.com") for _ in range(50)
    ]

    assert all(run == runs[0] for run in runs)
    assert [o.rule_id for o in runs[0]] == [o.rule_id for o in runs[-1]]  # order too
    assert len(runs[0]) >= 2


def test_ordering_is_by_urgency_then_rule_id(engine: OpportunityEngine, now: datetime) -> None:
    produced = engine.generate((EXPIRING, NO_DMARC), {}, now=now, domain="acme.com")
    ranks = [o.urgency.rank for o in produced]
    assert ranks == sorted(ranks)


# ---------------------------------------------------------------- the chain


def test_a_finding_becomes_an_opportunity_carrying_its_evidence(
    engine: OpportunityEngine, now: datetime
) -> None:
    """Rule -> Evidence -> Opportunity. The chain must stay traceable."""
    produced = engine.generate((EXPIRING,), {}, now=now, domain="acme.com")
    opportunity = next(o for o in produced if o.rule_id == "ssl_renewal")

    assert "TLS-04" in opportunity.triggered_by
    assert opportunity.evidence["TLS-04"]["days_remaining"] == 9
    assert opportunity.pitch_angle


def test_the_description_states_the_specific_fact(engine: OpportunityEngine, now: datetime) -> None:
    """Generic text is a defect. The number must be in the sentence."""
    produced = engine.generate((EXPIRING,), {}, now=now, domain="acme.com")
    opportunity = next(o for o in produced if o.rule_id == "ssl_renewal")

    assert "9 days" in opportunity.description
    assert "acme.com" in opportunity.description


def test_a_passing_finding_produces_no_opportunity(
    engine: OpportunityEngine, now: datetime
) -> None:
    healthy = _finding("TLS-04", {"days_remaining": 300}, status=FindingStatus.PASS)
    produced = engine.generate((healthy,), {}, now=now, domain="acme.com")
    assert not [o for o in produced if o.rule_id == "ssl_renewal"]


# ---------------------------------------------------------------- specificity gate


def test_an_unfillable_template_produces_nothing(engine: OpportunityEngine, now: datetime) -> None:
    """The gate that decides whether users trust the whole report.

    TLS-04 failed, but the evidence has no days_remaining to put in the
    sentence. 'Your certificate expires soon' is worse than silence.
    """
    vague = _finding("TLS-04", {"issuer": "Some CA"})
    produced = engine.generate((vague,), {}, now=now, domain="acme.com")

    assert not [o for o in produced if o.rule_id == "ssl_renewal"]


def test_no_opportunity_can_exist_without_evidence() -> None:
    with pytest.raises(ValueError, match="evidence"):
        Opportunity(
            rule_id=RuleId("x"),
            title="t",
            category=OpportunityCategory.SECURITY,
            urgency=Urgency.LOW,
            description="d",
            pitch_angle="p",
            evidence={},
            triggered_by=("X-01",),
        )


def test_no_opportunity_can_exist_without_naming_its_trigger() -> None:
    with pytest.raises(ValueError, match="triggered"):
        Opportunity(
            rule_id=RuleId("x"),
            title="t",
            category=OpportunityCategory.SECURITY,
            urgency=Urgency.LOW,
            description="d",
            pitch_angle="p",
            evidence={"a": 1},
            triggered_by=(),
        )


# ---------------------------------------------------------------- merging


def test_expired_supersedes_expiring(engine: OpportunityEngine, now: datetime) -> None:
    """A site with an expired certificate must not also be told it is
    expiring — that reads as a machine that has not understood."""
    expired = _finding("TLS-03", {"days_expired": 5, "not_after": "2026-07-25T00:00:00Z"})
    also_expiring = _finding("TLS-04", {"days_remaining": 0, "not_after": "2026-07-25T00:00:00Z"})

    rule_ids = {
        str(o.rule_id)
        for o in engine.generate((expired, also_expiring), {}, now=now, domain="acme.com")
    }

    assert "ssl_expired" in rule_ids
    assert "ssl_renewal" not in rule_ids


# ---------------------------------------------------------------- composition


def test_a_rule_may_require_several_findings(engine: OpportunityEngine, now: datetime) -> None:
    """no CDN AND slow TTFB -> a performance opportunity neither justifies
    on its own."""
    slow = _finding("PERF-01", {"ttfb_ms": 3200, "threshold_ms": 1500})
    no_cdn = _finding("PERF-03", {"headers_checked": []})

    with_both = {
        str(o.rule_id) for o in engine.generate((slow, no_cdn), {}, now=now, domain="acme.com")
    }
    with_one = {str(o.rule_id) for o in engine.generate((slow,), {}, now=now, domain="acme.com")}

    assert "performance_no_cdn" in with_both
    assert "performance_no_cdn" not in with_one


def test_artifact_conditions_are_evaluated(engine: OpportunityEngine, now: datetime) -> None:
    artifacts = {"technologies": {"has_analytics": False}}
    rule_ids = {str(o.rule_id) for o in engine.generate((), artifacts, now=now, domain="acme.com")}
    assert "no_analytics" in rule_ids


# ---------------------------------------------------------------- the AI boundary


def test_v1_ships_the_null_rewriter_and_calls_no_model() -> None:
    opportunity = Opportunity(
        rule_id=RuleId("x"),
        title="t",
        category=OpportunityCategory.SECURITY,
        urgency=Urgency.LOW,
        description="Deterministic text.",
        pitch_angle="p",
        evidence={"a": 1},
        triggered_by=("X-01",),
    )
    assert NullRewriter().rewrite(opportunity) == "Deterministic text."
    assert apply_rewriter(opportunity, NullRewriter()).description_ai is None


def test_a_rewrite_never_replaces_the_deterministic_description() -> None:
    original = Opportunity(
        rule_id=RuleId("ssl_renewal"),
        title="t",
        category=OpportunityCategory.SECURITY,
        urgency=Urgency.CRITICAL,
        description="The certificate expires in 9 days.",
        pitch_angle="p",
        evidence={"days_remaining": 9},
        triggered_by=("TLS-04",),
    )
    rewritten = original.with_rewrite("Their certificate lapses in 9 days.")

    assert rewritten.description == original.description
    assert rewritten.description_ai == "Their certificate lapses in 9 days."
    assert rewritten.evidence == original.evidence
    assert rewritten.urgency is original.urgency


@pytest.mark.parametrize(
    ("original", "candidate", "safe"),
    [
        ("Expires in 9 days.", "Lapses in 9 days.", True),
        ("Expires in 9 days.", "Expires soon.", True),  # dropping numbers is fine
        ("Expires in 9 days.", "Expired 40 days ago.", False),  # inventing one is not
        ("Expires in 9 days.", "", False),
    ],
)
def test_a_rewrite_inventing_a_number_is_rejected(
    original: str, candidate: str, safe: bool
) -> None:
    """The failure that actually matters: a hallucinated figure landing in
    an email a user sends to a prospect."""
    assert rewrite_is_safe(original, candidate)[0] is safe


def test_a_failing_rewriter_never_breaks_the_pipeline() -> None:
    class Exploding:
        def rewrite(self, opportunity: Opportunity) -> str:
            raise RuntimeError("model unavailable")

    opportunity = Opportunity(
        rule_id=RuleId("x"),
        title="t",
        category=OpportunityCategory.SECURITY,
        urgency=Urgency.LOW,
        description="Deterministic text.",
        pitch_angle="p",
        evidence={"a": 1},
        triggered_by=("X-01",),
    )
    assert apply_rewriter(opportunity, Exploding()).display_description == "Deterministic text."


# ---------------------------------------------------------------- unobserved
# Regression. A live scan of httpbin.org timed out — the homepage was never
# fetched — and the engine still produced "No website analytics installed".
#
# The technologies plugin correctly publishes no has_analytics key when there
# are no pages to inspect. `artifact_falsy` then read the missing key as
# False. A key that was never published means the plugin could not evaluate,
# which is not the same as evaluating to False.


def test_a_missing_artifact_does_not_satisfy_artifact_falsy(
    engine: OpportunityEngine, now: datetime
) -> None:
    """The httpbin.org false positive: no crawl, therefore no claim."""
    produced = engine.generate((), {}, now=now, domain="httpbin.org")

    assert "no_analytics" not in {o.rule_id for o in produced}


def test_a_published_false_artifact_still_satisfies_artifact_falsy(
    engine: OpportunityEngine, now: datetime
) -> None:
    """The fix must not silence the real case: we looked, and there is none."""
    artifacts = {"technologies": {"has_analytics": False}}
    produced = engine.generate((), artifacts, now=now, domain="acme.com")

    assert "no_analytics" in {o.rule_id for o in produced}


def test_a_missing_artifact_does_not_satisfy_artifact_truthy(
    engine: OpportunityEngine, now: datetime
) -> None:
    artifacts: dict[str, dict[str, object]] = {"technologies": {}}
    produced = engine.generate((), artifacts, now=now, domain="acme.com")

    assert "cookie_consent_missing" not in {o.rule_id for o in produced}


def test_a_failed_crawl_produces_no_website_opportunities(
    engine: OpportunityEngine, now: datetime
) -> None:
    """Everything we can still say must come from DNS, which is collected
    independently of the HTTP fetch."""
    produced = engine.generate((NO_DMARC,), {}, now=now, domain="httpbin.org")

    rule_ids = {o.rule_id for o in produced}
    assert "no_analytics" not in rule_ids
    assert rule_ids, "DNS-derived opportunities should survive a failed crawl"
