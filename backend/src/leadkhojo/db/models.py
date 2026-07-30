"""ORM models — eight tables.

    scans ──┬── businesses ──┬── site_snapshots  (1:1)
            │                ├── findings
            │                ├── opportunities
            │                └── business_scores (1:1)
            ├── reports
            └── jobs

Everything hangs off `scans`, which is what makes the future multi-tenancy
migration a single nullable column on one table rather than a schema-wide
change (see docs/12-SAAS-MIGRATION-PLAN.md).

Deleting a scan deletes everything beneath it. There is no soft delete: a
scan the user removed should actually be gone.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadkhojo.db.base import Base, JsonColumn, TimestampMixin, UuidColumn, UuidPrimaryKey


class Scan(Base, UuidPrimaryKey, TimestampMixin):
    """One user request. The root of everything."""

    __tablename__ = "scans"

    keyword: Mapped[str | None] = mapped_column(String(255))
    location: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="csv_import")
    result_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=25)

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)

    total_businesses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    current_business: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)

    # Set when this scan re-runs an earlier one, so results can be compared.
    rerun_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidColumn, ForeignKey("scans.id", ondelete="SET NULL")
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    businesses: Mapped[list[Business]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", passive_deletes=True
    )
    reports: Mapped[list[Report]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint("result_limit BETWEEN 1 AND 500", name="result_limit_range"),
        Index("ix_scans__status_created", "status", "created_at"),
    )

    @property
    def percent_complete(self) -> int:
        if not self.total_businesses:
            return 0
        done = self.completed_count + self.failed_count
        return min(100, int(done / self.total_businesses * 100))

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")


class Business(Base, UuidPrimaryKey, TimestampMixin):
    """One discovered company within one scan."""

    __tablename__ = "businesses"

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UuidColumn, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(512), nullable=False)
    website_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    final_url: Mapped[str | None] = mapped_column(Text)

    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(128))
    country_code: Mapped[str | None] = mapped_column(String(2))
    category: Mapped[str | None] = mapped_column(String(128))
    source_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="csv_import")
    source_external_id: Mapped[str | None] = mapped_column(String(255))

    # Discovery-provider fields may be subject to caching limits (Google
    # Places). NULL means no expiry — crawled data is ours and never expires.
    source_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    failure_reason: Mapped[str | None] = mapped_column(String(32))
    failure_detail: Mapped[str | None] = mapped_column(Text)

    # Flattened for list queries so the results table needs no joins.
    primary_email: Mapped[str | None] = mapped_column(String(320))
    primary_phone: Mapped[str | None] = mapped_column(String(32))
    contacts: Mapped[list[Any]] = mapped_column(JsonColumn, default=list)
    technologies: Mapped[list[Any]] = mapped_column(JsonColumn, default=list)
    artifacts: Mapped[dict[str, Any]] = mapped_column(JsonColumn, default=dict)

    crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    scan: Mapped[Scan] = relationship(back_populates="businesses")
    snapshot: Mapped[SiteSnapshotRecord | None] = relationship(
        back_populates="business",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    findings: Mapped[list[FindingRecord]] = relationship(
        back_populates="business", cascade="all, delete-orphan", passive_deletes=True
    )
    opportunities: Mapped[list[OpportunityRecord]] = relationship(
        back_populates="business", cascade="all, delete-orphan", passive_deletes=True
    )
    scores: Mapped[BusinessScore | None] = relationship(
        back_populates="business",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )

    __table_args__ = (
        # THE deduplication guarantee. domain is nullable and many NULLs are
        # permitted, so businesses without a website coexist happily.
        UniqueConstraint("scan_id", "domain", name="scan_domain"),
        Index("ix_businesses__scan_status", "scan_id", "status"),
    )


class SiteSnapshotRecord(Base, UuidPrimaryKey, TimestampMixin):
    """The raw crawl capture. Everything downstream is derived from this.

    Stored whole as JSON because analyzers read it as a unit and never query
    inside it. Normalising pages, headers and DNS into six tables would add
    joins and migrations for no benefit.
    """

    __tablename__ = "site_snapshots"

    business_id: Mapped[uuid.UUID] = mapped_column(
        UuidColumn, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    status: Mapped[str] = mapped_column(String(16), nullable=False)
    render_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="http")
    final_url: Mapped[str | None] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    failure_reason: Mapped[str | None] = mapped_column(String(32))

    # The full SiteSnapshot.to_dict() payload. Shape documented in
    # docs/05-DATABASE-SCHEMA.md section 4 and treated as a contract.
    payload: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)

    page_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    business: Mapped[Business] = relationship(back_populates="snapshot")


class FindingRecord(Base, UuidPrimaryKey, TimestampMixin):
    __tablename__ = "findings"

    business_id: Mapped[uuid.UUID] = mapped_column(
        UuidColumn, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )

    check_id: Mapped[str] = mapped_column(String(48), nullable=False)
    plugin_id: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(12), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # NOT NULL: a finding without evidence is not shippable.
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)
    remediation: Mapped[str | None] = mapped_column(Text)

    business: Mapped[Business] = relationship(back_populates="findings")

    __table_args__ = (
        UniqueConstraint("business_id", "check_id", name="business_check"),
        Index("ix_findings__business_severity", "business_id", "severity", "status"),
    )


class OpportunityRecord(Base, UuidPrimaryKey, TimestampMixin):
    """The table the user actually cares about."""

    __tablename__ = "opportunities"

    business_id: Mapped[uuid.UUID] = mapped_column(
        UuidColumn, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )

    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    urgency: Mapped[str] = mapped_column(String(12), nullable=False)

    # The deterministic text produced by the rule engine. Source of truth.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # An optional AI rephrasing. NEVER overwrites `description`; both are kept.
    description_ai: Mapped[str | None] = mapped_column(Text)

    pitch_angle: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)
    triggered_by: Mapped[list[Any]] = mapped_column(JsonColumn, nullable=False, default=list)

    business: Mapped[Business] = relationship(back_populates="opportunities")

    __table_args__ = (
        UniqueConstraint("business_id", "rule_id", name="business_rule"),
        Index("ix_opportunities__business_urgency", "business_id", "urgency"),
    )


class BusinessScore(Base, TimestampMixin):
    """Four independent scores, each with its component breakdown."""

    __tablename__ = "business_scores"

    business_id: Mapped[uuid.UUID] = mapped_column(
        UuidColumn, ForeignKey("businesses.id", ondelete="CASCADE"), primary_key=True
    )

    lead_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    website_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    security_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    opportunity_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    # NOT NULL: a score the user cannot explain is a score they cannot act on.
    breakdowns: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)

    business: Mapped[Business] = relationship(back_populates="scores")

    __table_args__ = (
        CheckConstraint("lead_score BETWEEN 0 AND 100", name="lead_range"),
        CheckConstraint("website_score BETWEEN 0 AND 100", name="website_range"),
        CheckConstraint("security_score BETWEEN 0 AND 100", name="security_range"),
        CheckConstraint("opportunity_score BETWEEN 0 AND 100", name="opportunity_range"),
        Index("ix_business_scores__opportunity", "opportunity_score"),
    )


class Report(Base, UuidPrimaryKey, TimestampMixin):
    """A generated CSV or PDF, cached so a repeat download is instant."""

    __tablename__ = "reports"

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UuidColumn, ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    business_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidColumn, ForeignKey("businesses.id", ondelete="CASCADE")
    )

    kind: Mapped[str] = mapped_column(
        String(24), nullable=False
    )  # csv | pdf_summary | pdf_business
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    scan: Mapped[Scan] = relationship(back_populates="reports")

    __table_args__ = (Index("ix_reports__scan_kind", "scan_id", "kind"),)


class Job(Base, UuidPrimaryKey, TimestampMixin):
    """Background work.

    Claimed with FOR UPDATE SKIP LOCKED on PostgreSQL, which is what lets
    several workers — and later several processes — poll the same table
    without double-claiming.
    """

    __tablename__ = "jobs"

    scan_id: Mapped[uuid.UUID | None] = mapped_column(
        UuidColumn, ForeignKey("scans.id", ondelete="CASCADE")
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=100)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)

    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # The claim query's exact access path.
        Index("ix_jobs__claimable", "status", "priority", "run_after"),
        Index("ix_jobs__scan", "scan_id", "status"),
    )


__all__ = [
    "Base",
    "Business",
    "BusinessScore",
    "FindingRecord",
    "Job",
    "OpportunityRecord",
    "Report",
    "Scan",
    "SiteSnapshotRecord",
]
