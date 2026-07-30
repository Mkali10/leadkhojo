"""Shared domain types.

Everything here is used across module boundaries. Nothing here knows about
the database, HTTP, or any specific plugin.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType

# Value types --------------------------------------------------------------
# NewType rather than bare `str` so a Domain cannot be passed where a Url is
# expected. Costs nothing at runtime, catches a real class of mistake.

Domain = NewType("Domain", str)  # canonical registrable domain: "acme.co.uk"
Url = NewType("Url", str)
CheckId = NewType("CheckId", str)  # "TLS-04" — stable, appears in exports
PluginId = NewType("PluginId", str)  # "ssl"
TechnologyId = NewType("TechnologyId", str)  # "wordpress"
RuleId = NewType("RuleId", str)  # "ssl_renewal"


class Severity(StrEnum):
    """How serious a finding is. Ordered by `rank` for sorting."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    @property
    def weight(self) -> float:
        """Contribution to score deductions."""
        return _SEVERITY_WEIGHT[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.INFO: 4,
}

_SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: 25.0,
    Severity.HIGH: 12.0,
    Severity.MEDIUM: 6.0,
    Severity.LOW: 2.0,
    Severity.INFO: 0.0,
}


class FindingStatus(StrEnum):
    """Outcome of a check.

    NOT_APPLICABLE is load-bearing: "we could not check" is not "you failed".
    A check that cannot evaluate must return NOT_APPLICABLE, never FAIL.
    """

    PASS = "pass"  # noqa: S105 - a check outcome, not a credential
    FAIL = "fail"
    WARN = "warn"
    INFO = "info"
    NOT_APPLICABLE = "not_applicable"

    @property
    def is_problem(self) -> bool:
        return self in (FindingStatus.FAIL, FindingStatus.WARN)


class Confidence(StrEnum):
    """How sure we are about a detection."""

    CERTAIN = "certain"
    LIKELY = "likely"
    POSSIBLE = "possible"

    @property
    def weight(self) -> float:
        return {"certain": 1.0, "likely": 0.7, "possible": 0.4}[self.value]


class Urgency(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"critical": 0, "high": 1, "medium": 2, "low": 3}[self.value]

    @property
    def weight(self) -> float:
        return {"critical": 30.0, "high": 20.0, "medium": 10.0, "low": 4.0}[self.value]


class OpportunityCategory(StrEnum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTENANCE = "maintenance"
    DEVELOPMENT = "development"
    MARKETING = "marketing"
    HOSTING = "hosting"
    COMPLIANCE = "compliance"


class TechCategory(StrEnum):
    CMS = "cms"
    ECOMMERCE = "ecommerce"
    FRAMEWORK = "framework"
    JAVASCRIPT = "javascript"
    LANGUAGE = "language"
    SERVER = "server"
    HOSTING = "hosting"
    CDN = "cdn"
    WAF = "waf"
    ANALYTICS = "analytics"
    MARKETING = "marketing"
    DATABASE_HINT = "database_hint"


class ContactKind(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    ADDRESS = "address"
    SOCIAL = "social"
    FORM = "form"


class ContactCategory(StrEnum):
    GENERAL = "general"
    SALES = "sales"
    SUPPORT = "support"
    CAREERS = "careers"
    SECURITY = "security"
    BILLING = "billing"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    OTHER = "other"


class CrawlFailure(StrEnum):
    """Why a crawl did not fully succeed.

    These are *data*, not exceptions. A failed crawl still produces a snapshot.
    """

    DNS_FAILURE = "dns_failure"
    CONNECTION_REFUSED = "connection_refused"
    TLS_ERROR = "tls_error"
    TIMEOUT = "timeout"
    HTTP_4XX = "http_4xx"
    HTTP_5XX = "http_5xx"
    ROBOTS_DENIED = "robots_denied"
    PARKED_DOMAIN = "parked_domain"
    RENDER_FAILURE = "render_failure"
    BLOCKED_ADDRESS = "blocked_address"


class SnapshotStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class RenderMode(StrEnum):
    HTTP = "http"
    PLAYWRIGHT = "playwright"


class PageType(StrEnum):
    HOME = "home"
    CONTACT = "contact"
    ABOUT = "about"
    PRIVACY = "privacy"
    LEGAL = "legal"
    OTHER = "other"
