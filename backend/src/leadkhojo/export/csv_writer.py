"""CSV export.

Two things that look like details and are not:

  * UTF-8 with BOM. Without it Excel mangles every non-ASCII business name,
    and the user's first impression of the product is broken text.
  * Formula injection guard. A business name beginning with =, +, - or @
    becomes an executable formula when opened in Excel.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from leadkhojo.core.types import FindingStatus
from leadkhojo.core.utils.clock import iso
from leadkhojo.pipeline.runner import BusinessResult

COLUMNS: tuple[str, ...] = (
    "business_name",
    "website",
    "domain",
    "city",
    "country",
    "status",
    "primary_email",
    "all_emails",
    "phone",
    "address",
    "linkedin",
    "facebook",
    "twitter",
    "instagram",
    "contact_form_url",
    "cms",
    "cms_version",
    "cms_outdated",
    "server",
    "cdn",
    "analytics",
    "technologies",
    "has_ssl",
    "ssl_expires_at",
    "ssl_days_remaining",
    "tls_version",
    "has_hsts",
    "has_csp",
    "has_spf",
    "has_dmarc",
    "dmarc_policy",
    "missing_headers_count",
    "critical_findings",
    "high_findings",
    "lead_score",
    "website_score",
    "security_score",
    "opportunity_score",
    "opportunity_count",
    "top_opportunity",
    "opportunities",
    "scanned_at",
)

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe(value: object) -> str:
    """Neutralise spreadsheet formula injection without altering the reading."""
    text = "" if value is None else str(value)
    if text and text[0] in _DANGEROUS_PREFIXES:
        return "'" + text
    return text


def _contacts_of(result: BusinessResult, kind: str, category: str | None = None) -> list[str]:
    contacts = result.artifact("contacts", "contacts", []) or []
    return [
        c["value"]
        for c in contacts
        if c.get("kind") == kind and (category is None or c.get("category") == category)
    ]


def _row(result: BusinessResult) -> dict[str, str]:
    business = result.business
    snapshot = result.snapshot

    emails = _contacts_of(result, "email")
    phones = _contacts_of(result, "phone")
    addresses = _contacts_of(result, "address")
    forms = _contacts_of(result, "form")

    technologies = result.artifact("technologies", "technologies", []) or []
    by_category: dict[str, list[dict[str, object]]] = {}
    for tech in technologies:
        by_category.setdefault(str(tech.get("category")), []).append(tech)

    cms = result.artifact("cms", "cms") or {}
    certificate = result.artifact("ssl", "certificate") or {}
    headers = result.artifact("headers", "security_headers", {}) or {}
    missing = result.artifact("headers", "missing_headers", []) or []
    opportunities = result.opportunities
    scores = result.scores

    def first(category: str) -> str:
        entries = by_category.get(category, [])
        return str(entries[0]["name"]) if entries else ""

    critical = sum(
        1
        for f in result.findings
        if f.status is FindingStatus.FAIL and f.severity.value == "critical"
    )
    high = sum(
        1 for f in result.findings if f.status is FindingStatus.FAIL and f.severity.value == "high"
    )

    return {
        "business_name": _safe(business.name),
        "website": _safe(business.website_url or ""),
        "domain": _safe(business.domain or ""),
        "city": _safe(business.city or ""),
        "country": _safe(business.country_code or ""),
        "status": _safe(
            "completed"
            if result.ok
            else (result.failure_reason.value if result.failure_reason else "failed")
        ),
        "primary_email": _safe(result.artifact("contacts", "primary_email") or ""),
        "all_emails": _safe("; ".join(emails)),
        "phone": _safe(phones[0] if phones else ""),
        "address": _safe(addresses[0] if addresses else ""),
        "linkedin": _safe(next(iter(_contacts_of(result, "social", "linkedin")), "")),
        "facebook": _safe(next(iter(_contacts_of(result, "social", "facebook")), "")),
        "twitter": _safe(next(iter(_contacts_of(result, "social", "twitter")), "")),
        "instagram": _safe(next(iter(_contacts_of(result, "social", "instagram")), "")),
        "contact_form_url": _safe(forms[0] if forms else ""),
        "cms": _safe(cms.get("name", "") if isinstance(cms, dict) else ""),
        "cms_version": _safe(cms.get("version", "") if isinstance(cms, dict) else ""),
        "cms_outdated": _safe(
            "yes"
            if isinstance(cms, dict) and cms.get("is_outdated") is True
            else ("no" if isinstance(cms, dict) and cms.get("is_outdated") is False else "unknown")
        ),
        "server": _safe(first("server")),
        "cdn": _safe(first("cdn")),
        "analytics": _safe("; ".join(str(t["name"]) for t in by_category.get("analytics", []))),
        "technologies": _safe("; ".join(str(t["name"]) for t in technologies)),
        "has_ssl": _safe("yes" if snapshot and snapshot.is_https else "no"),
        "ssl_expires_at": _safe((certificate or {}).get("not_after") or ""),
        "ssl_days_remaining": _safe((certificate or {}).get("days_remaining") or ""),
        "tls_version": _safe((certificate or {}).get("protocol") or ""),
        "has_hsts": _safe("yes" if headers.get("strict-transport-security") else "no"),
        "has_csp": _safe("yes" if headers.get("content-security-policy") else "no"),
        # "unknown", not "no", when the lookup itself failed. A false "no"
        # here becomes a false claim in a sales email.
        "has_spf": _safe(_yes_no(result, "spf", "TXT")),
        "has_dmarc": _safe(_yes_no(result, "dmarc", "DMARC")),
        "dmarc_policy": _safe(result.artifact("dns", "dmarc_policy") or ""),
        "missing_headers_count": _safe(len(missing)),
        "critical_findings": _safe(critical),
        "high_findings": _safe(high),
        "lead_score": _safe(scores.lead.total if scores else ""),
        "website_score": _safe(scores.website.total if scores else ""),
        "security_score": _safe(scores.security.total if scores else ""),
        "opportunity_score": _safe(scores.opportunity.total if scores else ""),
        "opportunity_count": _safe(len(opportunities)),
        "top_opportunity": _safe(opportunities[0].title if opportunities else ""),
        "opportunities": _safe(" | ".join(o.title for o in opportunities)),
        "scanned_at": _safe(iso(snapshot.captured_at) if snapshot else ""),
    }


def _yes_no(result: BusinessResult, key: str, lookup: str) -> str:
    """yes / no / unknown for a DNS record.

    "unknown" exists because an empty field has two causes: the record is
    genuinely absent, or the query never got an answer. Only the first is
    something we can tell a prospect.
    """
    if result.artifact("dns", key):
        return "yes"
    failed = result.artifact("dns", "lookup_failed") or ()
    return "unknown" if lookup in failed else "no"


def write_csv(results: Iterable[BusinessResult]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for result in results:
        writer.writerow(_row(result))
    # BOM so Excel detects UTF-8 rather than guessing the system codepage.
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


__all__ = ["COLUMNS", "write_csv"]
