"""SiteSnapshot — the boundary between network and analysis.

This is the most important contract in the codebase. The crawler is the only
component that produces one; every plugin consumes one and touches nothing
else. Changing these shapes is a breaking change that requires migrating the
whole fixture corpus.

Everything is frozen. A snapshot is a record of what a website served at one
moment; nothing downstream may edit it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Self

from leadkhojo.core.types import (
    CrawlFailure,
    Domain,
    PageType,
    RenderMode,
    SnapshotStatus,
    Url,
)
from leadkhojo.core.utils.clock import ensure_utc, iso

SNAPSHOT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PageCapture:
    url: Url
    final_url: Url
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    html: str = ""
    text: str = ""
    content_hash: str = ""
    bytes: int = 0
    response_time_ms: int = 0
    page_type: PageType = PageType.OTHER

    def header(self, name: str) -> str | None:
        """Case-insensitive header lookup. Headers are stored lowercased."""
        return self.headers.get(name.lower())

    @property
    def is_ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass(frozen=True, slots=True)
class TlsInfo:
    protocol: str | None = None
    cipher: str | None = None
    issuer: str | None = None
    subject: str | None = None
    sans: tuple[str, ...] = ()
    not_before: datetime | None = None
    not_after: datetime | None = None
    is_self_signed: bool = False
    chain_complete: bool = True
    hostname_matches: bool = True


@dataclass(frozen=True, slots=True)
class DnsInfo:
    """Public DNS records.

    A field being None means NXDOMAIN or no record — which is itself a finding.
    Plugins must distinguish "we looked and it was absent" (dns is present,
    dmarc is None) from "we never looked" (dns itself is None).
    """

    a: tuple[str, ...] = ()
    aaaa: tuple[str, ...] = ()
    mx: tuple[str, ...] = ()
    ns: tuple[str, ...] = ()
    txt: tuple[str, ...] = ()
    cname: str | None = None
    dmarc: str | None = None
    dkim_selectors: tuple[str, ...] = ()
    dnssec: bool = False
    resolved_ip: str | None = None

    @property
    def spf(self) -> str | None:
        for record in self.txt:
            if record.lower().startswith("v=spf1"):
                return record
        return None


@dataclass(frozen=True, slots=True)
class CookieInfo:
    name: str
    secure: bool = False
    http_only: bool = False
    same_site: str | None = None
    source_url: str = ""


@dataclass(frozen=True, slots=True)
class RobotsInfo:
    exists: bool = False
    disallowed_paths: tuple[str, ...] = ()
    sitemaps: tuple[str, ...] = ()
    blocked_us: bool = False


@dataclass(frozen=True, slots=True)
class Timings:
    dns_ms: int = 0
    connect_ms: int = 0
    ttfb_ms: int = 0
    total_ms: int = 0


@dataclass(frozen=True, slots=True)
class SiteSnapshot:
    """Everything the crawler saw. The sole input to every analyzer plugin."""

    domain: Domain
    requested_url: Url
    status: SnapshotStatus
    captured_at: datetime

    final_url: Url | None = None
    http_status: int | None = None
    render_mode: RenderMode = RenderMode.HTTP
    redirect_chain: tuple[str, ...] = ()
    failure_reason: CrawlFailure | None = None
    failure_detail: str | None = None

    pages: tuple[PageCapture, ...] = ()
    tls: TlsInfo | None = None
    dns: DnsInfo | None = None
    cookies: tuple[CookieInfo, ...] = ()
    robots: RobotsInfo | None = None
    timings: Timings = field(default_factory=Timings)

    duration_ms: int = 0
    schema_version: int = SNAPSHOT_SCHEMA_VERSION

    # -- convenience accessors for plugins ---------------------------------

    @property
    def home(self) -> PageCapture | None:
        for page in self.pages:
            if page.page_type is PageType.HOME:
                return page
        return self.pages[0] if self.pages else None

    @property
    def is_https(self) -> bool:
        target = self.final_url or self.requested_url
        return target.startswith("https://")

    @property
    def total_bytes(self) -> int:
        return sum(page.bytes for page in self.pages)

    def pages_of(self, page_type: PageType) -> tuple[PageCapture, ...]:
        return tuple(p for p in self.pages if p.page_type is page_type)

    def html_documents(self) -> tuple[str, ...]:
        return tuple(p.html for p in self.pages if p.html)

    def all_headers(self) -> dict[str, str]:
        """Headers from the homepage, which is what header checks assess."""
        home = self.home
        return dict(home.headers) if home else {}

    def with_pages(self, pages: tuple[PageCapture, ...]) -> Self:
        return replace(self, pages=pages)

    # -- serialization -----------------------------------------------------
    # Used for the fixture corpus and JSONB persistence. Round-tripping must
    # be lossless: a fixture is only useful if it reloads identically.

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["captured_at"] = iso(self.captured_at)
        if self.tls:
            data["tls"]["not_before"] = iso(self.tls.not_before) if self.tls.not_before else None
            data["tls"]["not_after"] = iso(self.tls.not_after) if self.tls.not_after else None
        return data

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SiteSnapshot:
        tls_raw = data.get("tls")
        tls = None
        if tls_raw:
            tls = TlsInfo(
                protocol=tls_raw.get("protocol"),
                cipher=tls_raw.get("cipher"),
                issuer=tls_raw.get("issuer"),
                subject=tls_raw.get("subject"),
                sans=tuple(tls_raw.get("sans") or ()),
                not_before=_parse_dt(tls_raw.get("not_before")),
                not_after=_parse_dt(tls_raw.get("not_after")),
                is_self_signed=bool(tls_raw.get("is_self_signed", False)),
                chain_complete=bool(tls_raw.get("chain_complete", True)),
                hostname_matches=bool(tls_raw.get("hostname_matches", True)),
            )

        dns_raw = data.get("dns")
        dns = None
        if dns_raw:
            dns = DnsInfo(
                a=tuple(dns_raw.get("a") or ()),
                aaaa=tuple(dns_raw.get("aaaa") or ()),
                mx=tuple(dns_raw.get("mx") or ()),
                ns=tuple(dns_raw.get("ns") or ()),
                txt=tuple(dns_raw.get("txt") or ()),
                cname=dns_raw.get("cname"),
                dmarc=dns_raw.get("dmarc"),
                dkim_selectors=tuple(dns_raw.get("dkim_selectors") or ()),
                dnssec=bool(dns_raw.get("dnssec", False)),
                resolved_ip=dns_raw.get("resolved_ip"),
            )

        robots_raw = data.get("robots")
        robots = None
        if robots_raw:
            robots = RobotsInfo(
                exists=bool(robots_raw.get("exists", False)),
                disallowed_paths=tuple(robots_raw.get("disallowed_paths") or ()),
                sitemaps=tuple(robots_raw.get("sitemaps") or ()),
                blocked_us=bool(robots_raw.get("blocked_us", False)),
            )

        timings_raw = data.get("timings") or {}

        return cls(
            domain=Domain(data["domain"]),
            requested_url=Url(data["requested_url"]),
            status=SnapshotStatus(data["status"]),
            captured_at=_parse_dt(data["captured_at"]) or datetime(1970, 1, 1, tzinfo=UTC),
            final_url=Url(data["final_url"]) if data.get("final_url") else None,
            http_status=data.get("http_status"),
            render_mode=RenderMode(data.get("render_mode", "http")),
            redirect_chain=tuple(data.get("redirect_chain") or ()),
            failure_reason=(
                CrawlFailure(data["failure_reason"]) if data.get("failure_reason") else None
            ),
            failure_detail=data.get("failure_detail"),
            pages=tuple(
                PageCapture(
                    url=Url(p["url"]),
                    final_url=Url(p.get("final_url", p["url"])),
                    status=int(p.get("status", 0)),
                    headers={k.lower(): v for k, v in (p.get("headers") or {}).items()},
                    html=p.get("html", ""),
                    text=p.get("text", ""),
                    content_hash=p.get("content_hash", ""),
                    bytes=int(p.get("bytes", 0)),
                    response_time_ms=int(p.get("response_time_ms", 0)),
                    page_type=PageType(p.get("page_type", "other")),
                )
                for p in (data.get("pages") or ())
            ),
            tls=tls,
            dns=dns,
            cookies=tuple(
                CookieInfo(
                    name=c["name"],
                    secure=bool(c.get("secure", False)),
                    http_only=bool(c.get("http_only", False)),
                    same_site=c.get("same_site"),
                    source_url=c.get("source_url", ""),
                )
                for c in (data.get("cookies") or ())
            ),
            robots=robots,
            timings=Timings(
                dns_ms=int(timings_raw.get("dns_ms", 0)),
                connect_ms=int(timings_raw.get("connect_ms", 0)),
                ttfb_ms=int(timings_raw.get("ttfb_ms", 0)),
                total_ms=int(timings_raw.get("total_ms", 0)),
            ),
            duration_ms=int(data.get("duration_ms", 0)),
            schema_version=int(data.get("schema_version", SNAPSHOT_SCHEMA_VERSION)),
        )

    @classmethod
    def from_json(cls, raw: str) -> SiteSnapshot:
        return cls.from_dict(json.loads(raw))

    @classmethod
    def failed_snapshot(
        cls,
        *,
        domain: Domain,
        requested_url: Url,
        reason: CrawlFailure,
        detail: str,
        captured_at: datetime,
        dns: DnsInfo | None = None,
    ) -> SiteSnapshot:
        """A crawl that could not complete still produces a snapshot.

        DNS may have resolved even when HTTP failed, and DNS-only findings
        (SPF, DMARC) are still worth surfacing. A failure is data.
        """
        return cls(
            domain=domain,
            requested_url=requested_url,
            status=SnapshotStatus.FAILED,
            captured_at=captured_at,
            failure_reason=reason,
            failure_detail=detail,
            dns=dns,
        )


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    try:
        return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None
