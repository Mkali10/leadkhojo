"""Lead scoring tests.

Four independent scores. They are independent by design: a security firm
sorts by Opportunity, a design agency by Website Quality ascending, a
generalist by Lead Quality. One blended number would serve none of them.

Every score exposes its component breakdown — a score the user cannot
explain is a score they cannot act on.
"""

from __future__ import annotations

import pytest

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
from leadkhojo.opportunities.schemas import Opportunity
from leadkhojo.scoring.engine import (
    compute_scores,
    score_lead,
    score_opportunity,
    score_security,
    score_website,
)


def _finding(
    check_id: str,
    status: FindingStatus = FindingStatus.FAIL,
    severity: Severity = Severity.HIGH,
) -> Finding:
    return Finding(
        check_id=CheckId(check_id),
        plugin_id=PluginId("test"),
        category="test",
        status=status,
        severity=severity,
        title=check_id,
        description="",
        evidence={"seen": True} if status.is_problem else {},
    )


def _opportunity(rule_id: str, urgency: Urgency) -> Opportunity:
    return Opportunity(
        rule_id=RuleId(rule_id),
        title=rule_id,
        category=OpportunityCategory.SECURITY,
        urgency=urgency,
        description="d",
        pitch_angle="p",
        evidence={"a": 1},
        triggered_by=("X-01",),
    )


CONTACTABLE = {"contacts": {"primary_email": "info@acme.com", "contacts": [{"kind": "email"}]}}


# ---------------------------------------------------------------- shape


def test_every_score_is_bounded_and_explains_itself() -> None:
    scores = compute_scores((_finding("TLS-01"),), (), CONTACTABLE)

    for breakdown in (scores.lead, scores.website, scores.security, scores.opportunity):
        assert 0 <= breakdown.total <= 100
        assert breakdown.components, "a score without a breakdown is not shippable"
        assert 0.0 <= breakdown.confidence <= 1.0


def test_scores_are_deterministic() -> None:
    findings = (_finding("TLS-04"), _finding("DNS-03"))
    runs = [compute_scores(findings, (), CONTACTABLE).to_dict() for _ in range(20)]
    assert all(run == runs[0] for run in runs)


def test_the_four_scores_are_independent() -> None:
    """A site can be secure and unreachable, or broken and easy to contact."""
    findings = (_finding("TLS-01"), _finding("PERF-04"))
    with_contact = compute_scores(findings, (), CONTACTABLE)
    without_contact = compute_scores(findings, (), {"contacts": {}})

    # Contactability moves lead and opportunity, but not security.
    assert with_contact.security.total == without_contact.security.total
    assert with_contact.lead.total > without_contact.lead.total


# ---------------------------------------------------------------- security


def test_a_clean_site_scores_high_on_security() -> None:
    passing = tuple(
        _finding(c, FindingStatus.PASS, Severity.INFO)
        for c in ("TLS-01", "TLS-03", "TLS-04", "HDR-01", "HDR-02", "DNS-01", "DNS-03")
    )
    assert score_security(passing).total >= 80


def test_failures_reduce_the_security_score() -> None:
    failing = tuple(_finding(c) for c in ("TLS-01", "HDR-01", "HDR-02", "DNS-01", "DNS-03"))
    passing = tuple(
        _finding(c, FindingStatus.PASS, Severity.INFO)
        for c in ("TLS-01", "HDR-01", "HDR-02", "DNS-01", "DNS-03")
    )
    assert score_security(failing).total < score_security(passing).total


def test_a_critical_finding_cuts_through_group_averages() -> None:
    ordinary = (_finding("HDR-01", severity=Severity.LOW),)
    critical = (_finding("TLS-03", severity=Severity.CRITICAL),)
    assert score_security(critical).total < score_security(ordinary).total


def test_unevaluable_checks_lower_confidence_rather_than_the_score() -> None:
    """A site we could not check is not a site that failed."""
    unknown = tuple(
        _finding(c, FindingStatus.NOT_APPLICABLE, Severity.INFO)
        for c in ("DNS-01", "DNS-02", "DNS-03", "DNS-04")
    )
    result = score_security(unknown)

    assert result.confidence < 1.0
    assert result.total > 0, "missing data must not be scored as failure"


# ---------------------------------------------------------------- website


def test_an_unknown_cms_version_is_neutral_not_punitive() -> None:
    """None means 'we could not tell', which must not be treated as bad."""
    unknown = {"cms": {"cms": {"is_outdated": None}}}
    outdated = {"cms": {"cms": {"is_outdated": True}}}
    current = {"cms": {"cms": {"is_outdated": False}}}

    findings = (_finding("PERF-01", FindingStatus.PASS, Severity.INFO),)
    unknown_score = score_website(findings, unknown).total
    outdated_score = score_website(findings, outdated).total
    current_score = score_website(findings, current).total

    assert outdated_score < unknown_score < current_score


def test_a_missing_viewport_costs_the_mobile_component() -> None:
    with_viewport = score_website((_finding("PERF-04", FindingStatus.PASS, Severity.INFO),), {})
    without = score_website((_finding("PERF-04"),), {})
    assert without.components["mobile"] < with_viewport.components["mobile"]


# ---------------------------------------------------------------- lead


def test_contactability_dominates_lead_quality() -> None:
    reachable = score_lead((), CONTACTABLE)
    unreachable = score_lead((), {"contacts": {}})
    assert reachable.total > unreachable.total
    assert reachable.components["contactability"] > 0


def test_a_phone_is_worth_less_than_an_email_but_more_than_nothing() -> None:
    email_only = score_lead((), {"contacts": {"primary_email": "a@b.com", "contacts": []}})
    phone_only = score_lead((), {"contacts": {"primary_phone": "+15125550142", "contacts": []}})
    nothing = score_lead((), {"contacts": {}})

    assert email_only.total > phone_only.total > nothing.total


def test_confidence_drops_when_no_contacts_were_found() -> None:
    assert score_lead((), {"contacts": {}}).confidence < 1.0


# ---------------------------------------------------------------- opportunity


def test_urgent_opportunities_are_worth_more() -> None:
    critical = (_opportunity("a", Urgency.CRITICAL),)
    low = (_opportunity("a", Urgency.LOW),)
    assert score_opportunity(critical, CONTACTABLE).total > score_opportunity(low, CONTACTABLE).total


def test_more_opportunities_score_higher() -> None:
    one = (_opportunity("a", Urgency.HIGH),)
    three = tuple(_opportunity(x, Urgency.HIGH) for x in "abc")
    assert score_opportunity(three, CONTACTABLE).total > score_opportunity(one, CONTACTABLE).total


def test_an_unreachable_prospect_is_worth_little_however_broken_the_site() -> None:
    """You cannot sell to someone you cannot contact. This is the rule that
    stops the list filling with unreachable rows at the top."""
    opportunities = tuple(_opportunity(x, Urgency.CRITICAL) for x in "abcd")

    reachable = score_opportunity(opportunities, CONTACTABLE).total
    unreachable = score_opportunity(opportunities, {"contacts": {}}).total

    assert unreachable < reachable / 1.5


def test_no_opportunities_scores_zero_ish() -> None:
    assert score_opportunity((), CONTACTABLE).total < 20


@pytest.mark.parametrize("artifacts", [{}, {"contacts": {}}, {"technologies": {}}])
def test_missing_artifacts_never_raise(artifacts: dict) -> None:
    scores = compute_scores((), (), artifacts)
    assert 0 <= scores.lead.total <= 100
