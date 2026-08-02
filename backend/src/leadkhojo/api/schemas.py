"""API request and response models.

These are the contract the React UI consumes. Two rules shape them:

  * The results row carries everything the table renders, so the UI needs
    no follow-up request per row.
  * Nothing is invented. A business with no contact returns null, not a
    guess — the no-synthesis rule survives all the way to the wire.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------- requests


class CreateScanRequest(BaseModel):
    """Start a scan from a keyword, or from an explicit list of URLs."""

    keyword: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    urls: list[str] = Field(default_factory=list, max_length=500)
    provider: Literal["csv_import", "manual"] = "manual"
    limit: int = Field(default=25, ge=1, le=500)

    @field_validator("urls")
    @classmethod
    def _strip(cls, value: list[str]) -> list[str]:
        return [u.strip() for u in value if u and u.strip()]

    def is_valid_request(self) -> bool:
        return bool(self.urls) or bool(self.keyword)


class CreateScanFromCsvRequest(BaseModel):
    csv_content: str = Field(min_length=1, max_length=5_000_000)
    limit: int = Field(default=500, ge=1, le=500)


# ---------------------------------------------------------------- responses


class ScanSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    keyword: str | None
    location: str | None
    provider: str
    total_businesses: int
    completed_count: int
    failed_count: int
    rerun_of_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ScanProgress(BaseModel):
    """The polling payload. Deliberately small — the UI hits it every 2s."""

    id: uuid.UUID
    status: str
    total_businesses: int
    completed_count: int
    failed_count: int
    percent_complete: int

    # Named so the UI can say "analyzing Northwind Dental" rather than
    # showing an anonymous spinner. A progress bar tells the user to wait;
    # a name tells them the thing is alive.
    current_business: str | None
    elapsed_seconds: int | None
    error_message: str | None


class ScoreSet(BaseModel):
    lead: int | None = None
    website: int | None = None
    security: int | None = None
    opportunity: int | None = None


class TechnologySummary(BaseModel):
    name: str
    category: str | None = None
    version: str | None = None
    is_outdated: bool | None = None


class OpportunitySummary(BaseModel):
    rule_id: str
    title: str
    category: str
    urgency: str


class BusinessRow(BaseModel):
    """One row of the results table.

    Carries everything the table sorts, filters or displays so rendering
    needs no per-row request.
    """

    id: uuid.UUID
    name: str
    domain: str | None
    website_url: str | None
    city: str | None
    country_code: str | None
    status: str
    failure_reason: str | None

    primary_email: str | None
    primary_phone: str | None
    contact_count: int

    scores: ScoreSet
    top_technologies: list[TechnologySummary]
    opportunity_count: int
    top_opportunity: OpportunitySummary | None
    critical_findings: int
    high_findings: int

    scanned_at: datetime | None


class FindingDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    check_id: str
    plugin_id: str
    category: str
    status: str
    severity: str
    title: str
    description: str
    evidence: dict[str, Any]
    remediation: str | None


class OpportunityDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_id: str
    title: str
    category: str
    urgency: str

    description: str
    """Deterministic, produced by the rule engine. The source of truth."""

    description_ai: str | None
    """Optional rephrasing. Never replaces `description`; both are returned
    so a client can always show the defensible version."""

    pitch_angle: str
    evidence: dict[str, Any]
    triggered_by: list[str]


class ContactDetail(BaseModel):
    kind: str
    category: str
    value: str
    source_url: str


class SnapshotMeta(BaseModel):
    captured_at: datetime
    render_mode: str
    status: str
    page_count: int
    duration_ms: int
    final_url: str | None


class BusinessDetail(BaseModel):
    id: uuid.UUID
    scan_id: uuid.UUID
    name: str
    domain: str | None
    website_url: str | None
    final_url: str | None
    city: str | None
    country_code: str | None
    status: str
    failure_reason: str | None
    failure_detail: str | None

    contacts: list[ContactDetail]
    primary_email: str | None
    primary_phone: str | None
    technologies: list[TechnologySummary]
    findings: list[FindingDetail]
    opportunities: list[OpportunityDetail]
    scores: dict[str, Any] | None
    snapshot: SnapshotMeta | None
    analyzed_at: datetime | None


class Pagination(BaseModel):
    total: int
    limit: int
    offset: int


class BusinessListResponse(BaseModel):
    data: list[BusinessRow]
    pagination: Pagination
    scan_status: str


class ScanListResponse(BaseModel):
    data: list[ScanSummary]
    pagination: Pagination


# ---------------------------------------------------------------- comparison


class ScoreDelta(BaseModel):
    before: int | None
    after: int | None
    change: int | None


class BusinessComparison(BaseModel):
    domain: str
    name: str
    state: Literal["added", "removed", "changed", "unchanged"]
    scores: dict[str, ScoreDelta] = Field(default_factory=dict)
    opportunities_gained: list[str] = Field(default_factory=list)
    opportunities_resolved: list[str] = Field(default_factory=list)
    technologies_added: list[str] = Field(default_factory=list)
    technologies_removed: list[str] = Field(default_factory=list)


class ScanComparison(BaseModel):
    """What changed between two scans of the same targets.

    The foundation of the monitoring product: 'their certificate is fine
    today but their DMARC disappeared' is a reason to call.
    """

    base_scan_id: uuid.UUID
    compare_scan_id: uuid.UUID
    total_compared: int
    added: int
    removed: int
    changed: int
    unchanged: int
    businesses: list[BusinessComparison]


# ---------------------------------------------------------------- meta


class PluginInfo(BaseModel):
    id: str
    name: str
    version: str
    kind: str
    depends_on: list[str]
    provides: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    database: bool
    rules_loaded: bool
    plugins: int
    workers_running: bool


class ProblemDetail(BaseModel):
    """RFC 9457. Every error says what happened and what to do next."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    correlation_id: str | None = None
    meta: dict[str, Any] | None = None


__all__ = [
    "BusinessComparison",
    "BusinessDetail",
    "BusinessListResponse",
    "BusinessRow",
    "ContactDetail",
    "CreateScanFromCsvRequest",
    "CreateScanRequest",
    "FindingDetail",
    "HealthResponse",
    "OpportunityDetail",
    "OpportunitySummary",
    "Pagination",
    "PluginInfo",
    "ProblemDetail",
    "ReadinessResponse",
    "ScanComparison",
    "ScanListResponse",
    "ScanProgress",
    "ScanSummary",
    "ScoreDelta",
    "ScoreSet",
    "SnapshotMeta",
    "TechnologySummary",
]
