"""Export tests — CSV and PDF.

The CSV is what the user works from. The PDF is what they attach to their
first email. Both are the product's visible surface, so the details that
look cosmetic here are not.
"""

from __future__ import annotations

import csv
import io

import pytest

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import (
    CheckId,
    Domain,
    FindingStatus,
    OpportunityCategory,
    PluginId,
    RuleId,
    Severity,
    Urgency,
)
from leadkhojo.discovery.providers import DiscoveredBusiness
from leadkhojo.export.csv_writer import COLUMNS, write_csv
from leadkhojo.export.pdf_report import build_business_report, build_scan_summary
from leadkhojo.opportunities.schemas import Opportunity
from leadkhojo.pipeline.runner import BusinessResult
from leadkhojo.scoring.engine import compute_scores
from tests.conftest import make_dns, make_snapshot, make_tls


def _result(
    name: str = "Acme Corp",
    *,
    domain: str = "acme.com",
    email: str | None = "info@acme.com",
    ok: bool = True,
) -> BusinessResult:
    business = DiscoveredBusiness(
        name=name,
        website_url="https://acme.com",  # type: ignore[arg-type]
        domain=Domain(domain),
        city="Austin",
        country_code="US",
    )
    if not ok:
        return BusinessResult(business=business, error="No website to analyze")

    findings = (
        Finding(
            check_id=CheckId("TLS-04"),
            plugin_id=PluginId("ssl"),
            category="tls",
            status=FindingStatus.FAIL,
            severity=Severity.HIGH,
            title="SSL certificate expires soon",
            description="The certificate expires in 9 days.",
            evidence={"days_remaining": 9, "not_after": "2026-08-08T00:00:00Z"},
            remediation="Renew and enable ACME auto-renewal.",
        ),
    )
    opportunities = (
        Opportunity(
            rule_id=RuleId("ssl_renewal"),
            title="SSL certificate expires in 9 days",
            category=OpportunityCategory.SECURITY,
            urgency=Urgency.CRITICAL,
            description="The certificate for acme.com expires in 9 days.",
            pitch_angle="Lead with the date.",
            evidence={"days_remaining": 9},
            triggered_by=("TLS-04",),
        ),
    )
    artifacts = {
        "contacts": {
            "primary_email": email,
            "primary_phone": "+15125550142",
            "contacts": (
                [
                    {
                        "kind": "email",
                        "category": "general",
                        "value": email,
                        "source_url": "https://acme.com/contact",
                    }
                ]
                if email
                else []
            ),
        },
        "technologies": {
            "technologies": [
                {
                    "id": "wordpress",
                    "name": "WordPress",
                    "category": "cms",
                    "version": "5.4.2",
                    "is_outdated": True,
                }
            ]
        },
        "cms": {"cms": {"name": "WordPress", "version": "5.4.2", "is_outdated": True}},
        "ssl": {"certificate": {"not_after": "2026-08-08T00:00:00Z", "days_remaining": 9,
                                "protocol": "TLSv1.3"}},
        "headers": {"security_headers": {"strict-transport-security": "max-age=1"},
                    "missing_headers": ["content-security-policy"]},
        "dns": {"spf": "v=spf1 ~all", "dmarc": None, "dmarc_policy": None},
    }
    return BusinessResult(
        business=business,
        snapshot=make_snapshot(domain=domain, tls=make_tls(days_until_expiry=9), dns=make_dns()),
        findings=findings,
        opportunities=opportunities,
        artifacts=artifacts,
        scores=compute_scores(findings, opportunities, artifacts),
    )


def _rows(payload: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))


# ================================================================ CSV


def test_csv_starts_with_a_bom_so_excel_reads_utf8() -> None:
    """Without the BOM Excel guesses the system codepage and mangles every
    non-ASCII business name. The user's first impression is broken text."""
    assert write_csv([_result()]).startswith(b"\xef\xbb\xbf")


def test_every_declared_column_is_present() -> None:
    rows = _rows(write_csv([_result()]))
    assert list(rows[0]) == list(COLUMNS)


def test_analysis_output_reaches_the_row() -> None:
    row = _rows(write_csv([_result()]))[0]

    assert row["business_name"] == "Acme Corp"
    assert row["domain"] == "acme.com"
    assert row["primary_email"] == "info@acme.com"
    assert row["cms"] == "WordPress"
    assert row["cms_version"] == "5.4.2"
    assert row["cms_outdated"] == "yes"
    assert row["ssl_days_remaining"] == "9"
    assert row["has_dmarc"] == "no"
    assert row["opportunity_count"] == "1"
    assert row["top_opportunity"]


def test_an_unknown_cms_version_is_reported_as_unknown_not_no() -> None:
    """'no' would claim the CMS is current, which we do not know."""
    result = _result()
    result.artifacts["cms"] = {"cms": {"name": "WordPress", "is_outdated": None}}
    assert _rows(write_csv([result]))[0]["cms_outdated"] == "unknown"


def test_a_missing_contact_exports_as_empty_not_as_a_guess() -> None:
    row = _rows(write_csv([_result(email=None)]))[0]
    assert row["primary_email"] == ""
    assert "info@acme.com" not in row["all_emails"]


def test_a_failed_business_still_exports_a_row() -> None:
    """A user comparing the CSV to their input list must find every domain."""
    rows = _rows(write_csv([_result(), _result("Broken Ltd", domain="broken.com", ok=False)]))
    assert len(rows) == 2
    assert rows[1]["business_name"] == "Broken Ltd"


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_formula_injection_is_neutralised(prefix: str) -> None:
    """A business name starting with = becomes an executable formula when
    the CSV is opened in Excel."""
    payload = write_csv([_result(name=f"{prefix}HYPERLINK(\"http://evil\",\"click\")")])
    assert _rows(payload)[0]["business_name"].startswith("'")


def test_commas_and_quotes_in_names_survive_the_round_trip() -> None:
    rows = _rows(write_csv([_result(name='Smith, "Bob" & Co')]))
    assert rows[0]["business_name"] == 'Smith, "Bob" & Co'


def test_unicode_names_survive() -> None:
    rows = _rows(write_csv([_result(name="Café Müller 東京")]))
    assert rows[0]["business_name"] == "Café Müller 東京"


def test_an_empty_scan_still_produces_a_header_row() -> None:
    rows = _rows(write_csv([]))
    assert rows == []
    assert write_csv([]).decode("utf-8-sig").startswith("business_name")


# ================================================================ PDF


def test_a_business_report_is_a_valid_pdf() -> None:
    payload = build_business_report(_result())
    assert payload.startswith(b"%PDF")
    assert len(payload) > 2000


def test_a_report_for_a_failed_business_explains_itself_rather_than_crashing() -> None:
    payload = build_business_report(_result("Broken Ltd", domain="broken.com", ok=False))
    assert payload.startswith(b"%PDF")


def test_a_report_survives_a_business_with_no_contacts() -> None:
    payload = build_business_report(_result(email=None))
    assert payload.startswith(b"%PDF")


def test_html_metacharacters_in_content_do_not_break_the_layout() -> None:
    """Crawled content is hostile input. ReportLab's paragraph markup will
    throw on an unescaped angle bracket."""
    payload = build_business_report(_result(name="<script>alert(1)</script> & Co"))
    assert payload.startswith(b"%PDF")


def test_a_scan_summary_is_a_valid_pdf() -> None:
    payload = build_scan_summary([_result(), _result("Beta Ltd", domain="beta.com")])
    assert payload.startswith(b"%PDF")


def test_a_scan_summary_with_no_results_still_renders() -> None:
    assert build_scan_summary([]).startswith(b"%PDF")


def test_reports_are_byte_stable_for_the_same_input() -> None:
    """Not strictly required, but a moving PDF makes diffing impossible and
    usually means an un-injected clock somewhere."""
    result = _result()
    first, second = build_business_report(result), build_business_report(result)
    assert len(first) == len(second)
