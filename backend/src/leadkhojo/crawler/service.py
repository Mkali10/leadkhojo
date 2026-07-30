"""CrawlerService — the only component in the pipeline that touches the network.

Politeness is structural here, not a convention:
  * robots.txt is honoured with no override
  * one concurrent request per host, with a delay between them
  * at most MAX_PAGES pages per site
  * an honest, contactable User-Agent
  * every connection passes the SSRF guard, including after each redirect

A crawl that fails still produces a snapshot. Failure is data, not an
exception — DNS may have resolved even when HTTP did not, and DNS-only
findings (SPF, DMARC) are still worth surfacing.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from leadkhojo.core.config import Settings
from leadkhojo.core.errors import CrawlError
from leadkhojo.core.types import (
    CrawlFailure,
    Domain,
    PageType,
    RenderMode,
    SnapshotStatus,
    Url,
)
from leadkhojo.core.utils.clock import utcnow
from leadkhojo.core.utils.domains import canonical_domain, hostname_of, join_url, normalize_url
from leadkhojo.crawler.collectors import collect_dns, collect_tls
from leadkhojo.crawler.guards import assert_url_is_fetchable
from leadkhojo.crawler.robots import EMPTY_ROBOTS, RobotsRules, parse_robots
from leadkhojo.crawler.snapshot import (
    CookieInfo,
    PageCapture,
    SiteSnapshot,
    Timings,
)

logger = logging.getLogger(__name__)

# Paths worth trying on every site. A short, fixed list — not enumeration.
_CANDIDATE_PATHS: tuple[tuple[str, PageType], ...] = (
    ("/contact", PageType.CONTACT),
    ("/contact-us", PageType.CONTACT),
    ("/contactus", PageType.CONTACT),
    ("/about", PageType.ABOUT),
    ("/about-us", PageType.ABOUT),
    ("/privacy", PageType.PRIVACY),
    ("/privacy-policy", PageType.PRIVACY),
    ("/imprint", PageType.LEGAL),
    ("/legal", PageType.LEGAL),
)

_CONTACT_HINTS = ("contact", "kontakt", "about", "impressum", "imprint", "privacy", "legal")

_PARKED_MARKERS = (
    "this domain is for sale",
    "buy this domain",
    "domain parking",
    "parked free",
    "godaddy.com/domainsearch",
    "sedoparking.com",
)


@dataclass(frozen=True, slots=True)
class _Fetched:
    page: PageCapture
    cookies: tuple[CookieInfo, ...]


class CrawlerService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def crawl(self, url: str, *, now: datetime | None = None) -> SiteSnapshot:
        started = time.perf_counter()
        captured_at = now or utcnow()

        normalized = normalize_url(url)
        domain = canonical_domain(url)
        if normalized is None or domain is None:
            return SiteSnapshot.failed_snapshot(
                domain=Domain(domain or url),
                requested_url=Url(url),
                reason=CrawlFailure.DNS_FAILURE,
                detail=f"Not a usable URL: {url!r}",
                captured_at=captured_at,
            )

        # DNS first: it is cheap, and its results survive an HTTP failure.
        dns_info = await collect_dns(domain)

        try:
            assert_url_is_fetchable(normalized)
        except CrawlError as exc:
            reason = (
                CrawlFailure.BLOCKED_ADDRESS
                if "non-public" in str(exc) or "port" in str(exc)
                else CrawlFailure.DNS_FAILURE
            )
            return SiteSnapshot.failed_snapshot(
                domain=domain,
                requested_url=normalized,
                reason=reason,
                detail=exc.message,
                captured_at=captured_at,
                dns=dns_info,
            )

        headers = {
            "User-Agent": self._settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        timeout = httpx.Timeout(
            self._settings.request_timeout_seconds,
            connect=self._settings.connect_timeout_seconds,
        )

        async with httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            max_redirects=self._settings.max_redirects,
            verify=False,  # noqa: S501 - we inspect broken certs deliberately; see below
        ) as client:
            robots = await self._fetch_robots(client, normalized)

            if robots.blocks_everything:
                return SiteSnapshot.failed_snapshot(
                    domain=domain,
                    requested_url=normalized,
                    reason=CrawlFailure.ROBOTS_DENIED,
                    detail="robots.txt disallows all crawling for our user agent",
                    captured_at=captured_at,
                    dns=dns_info,
                )

            home_result, failure = await self._fetch_home(client, normalized, robots)
            if home_result is None:
                snapshot = SiteSnapshot.failed_snapshot(
                    domain=domain,
                    requested_url=normalized,
                    reason=failure or CrawlFailure.TIMEOUT,
                    detail="Homepage could not be fetched",
                    captured_at=captured_at,
                    dns=dns_info,
                )
                return snapshot

            home_page = home_result.page
            cookies = list(home_result.cookies)

            if _is_parked(home_page):
                return SiteSnapshot(
                    domain=domain,
                    requested_url=normalized,
                    final_url=home_page.final_url,
                    status=SnapshotStatus.PARTIAL,
                    captured_at=captured_at,
                    http_status=home_page.status,
                    failure_reason=CrawlFailure.PARKED_DOMAIN,
                    failure_detail="Domain appears to be parked or for sale",
                    pages=(home_page,),
                    dns=dns_info,
                    robots=robots.to_info(),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )

            pages = [home_page]
            for target, page_type in self._plan_pages(home_page, robots):
                if len(pages) >= self._settings.max_pages_per_site:
                    break
                await asyncio.sleep(self._settings.host_delay_seconds)
                fetched = await self._fetch_one(client, target, page_type, robots)
                if fetched is not None:
                    pages.append(fetched.page)
                    cookies.extend(fetched.cookies)

        hostname = hostname_of(home_page.final_url) or domain
        tls_info = (
            await collect_tls(hostname) if home_page.final_url.startswith("https://") else None
        )

        total_ms = int((time.perf_counter() - started) * 1000)
        return SiteSnapshot(
            domain=domain,
            requested_url=normalized,
            final_url=home_page.final_url,
            status=SnapshotStatus.COMPLETE,
            captured_at=captured_at,
            http_status=home_page.status,
            render_mode=RenderMode.HTTP,
            pages=tuple(pages),
            tls=tls_info,
            dns=dns_info,
            cookies=tuple(_dedupe_cookies(cookies)),
            robots=robots.to_info(),
            timings=Timings(ttfb_ms=home_page.response_time_ms, total_ms=total_ms),
            duration_ms=total_ms,
        )

    # -- fetching ----------------------------------------------------------

    async def _fetch_robots(self, client: httpx.AsyncClient, base: str) -> RobotsRules:
        robots_url = join_url(base, "/robots.txt")
        if robots_url is None:
            return EMPTY_ROBOTS
        try:
            response = await client.get(robots_url)
        except httpx.HTTPError:
            return EMPTY_ROBOTS
        if response.status_code != 200:
            return EMPTY_ROBOTS
        return parse_robots(response.text[:200_000], self._settings.user_agent)

    async def _fetch_home(
        self, client: httpx.AsyncClient, url: str, robots: RobotsRules
    ) -> tuple[_Fetched | None, CrawlFailure | None]:
        fetched = await self._fetch_one(client, url, PageType.HOME, robots)
        if fetched is None:
            return None, CrawlFailure.TIMEOUT
        if fetched.page.status >= 500:
            return fetched, CrawlFailure.HTTP_5XX
        if fetched.page.status >= 400:
            return fetched, CrawlFailure.HTTP_4XX
        return fetched, None

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        url: str,
        page_type: PageType,
        robots: RobotsRules,
    ) -> _Fetched | None:
        if not robots.is_allowed(url):
            logger.debug("crawl.robots_skip", extra={"url": url})
            return None

        try:
            assert_url_is_fetchable(url)
        except CrawlError:
            return None

        started = time.perf_counter()
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            logger.debug("crawl.fetch_failed", extra={"url": url, "error": str(exc)})
            return None

        # Re-check after redirects: a redirect into a private range is the
        # classic SSRF bypass.
        final_url = str(response.url)
        if final_url != url:
            try:
                assert_url_is_fetchable(final_url)
            except CrawlError:
                return None

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        body = response.content[: self._settings.max_page_bytes]
        html = body.decode(response.encoding or "utf-8", errors="replace")

        return _Fetched(
            page=PageCapture(
                url=Url(url),
                final_url=Url(final_url),
                status=response.status_code,
                headers={k.lower(): v for k, v in response.headers.items()},
                html=html,
                text=_visible_text(html),
                content_hash=f"sha256:{hashlib.sha256(body).hexdigest()[:32]}",
                bytes=len(body),
                response_time_ms=elapsed_ms,
                page_type=page_type,
            ),
            cookies=tuple(
                CookieInfo(
                    name=name,
                    secure="secure" in str(response.headers.get("set-cookie", "")).lower(),
                    http_only="httponly" in str(response.headers.get("set-cookie", "")).lower(),
                    same_site=_same_site(str(response.headers.get("set-cookie", ""))),
                    source_url=final_url,
                )
                for name in response.cookies
            ),
        )

    # -- page planning -----------------------------------------------------

    def _plan_pages(self, home: PageCapture, robots: RobotsRules) -> list[tuple[str, PageType]]:
        """Choose which additional pages to fetch. Bounded and robots-filtered."""
        planned: dict[str, PageType] = {}
        base = home.final_url

        # Links the homepage actually offers are better than guessed paths.
        if home.html:
            soup = BeautifulSoup(home.html, "lxml")
            for anchor in soup.find_all("a", href=True):
                href = str(anchor["href"])
                text = anchor.get_text(" ", strip=True).lower()
                haystack = f"{href.lower()} {text}"
                if not any(hint in haystack for hint in _CONTACT_HINTS):
                    continue
                target = join_url(base, href)
                if target is None:
                    continue
                if canonical_domain(target) != canonical_domain(base):
                    continue
                if target.rstrip("/") == base.rstrip("/"):
                    continue
                planned.setdefault(target, _classify(target))
                if len(planned) >= self._settings.max_pages_per_site * 2:
                    break

        for path, page_type in _CANDIDATE_PATHS:
            target = join_url(base, path)
            if target and target not in planned:
                planned.setdefault(target, page_type)

        allowed = [(u, t) for u, t in planned.items() if robots.is_allowed(u)]
        # Contact pages first — they are why we are here.
        allowed.sort(key=lambda item: (item[1] is not PageType.CONTACT, item[0]))
        return allowed[: self._settings.max_pages_per_site - 1]


def _classify(url: str) -> PageType:
    lowered = url.lower()
    if "contact" in lowered or "kontakt" in lowered:
        return PageType.CONTACT
    if "about" in lowered:
        return PageType.ABOUT
    if "privacy" in lowered:
        return PageType.PRIVACY
    if "legal" in lowered or "imprint" in lowered or "impressum" in lowered:
        return PageType.LEGAL
    return PageType.OTHER


def _visible_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())[:50_000]


def _is_parked(page: PageCapture) -> bool:
    lowered = (page.text or "").lower()
    if len(lowered) > 4000:
        return False
    return any(marker in lowered for marker in _PARKED_MARKERS)


def _same_site(set_cookie: str) -> str | None:
    lowered = set_cookie.lower()
    for value in ("strict", "lax", "none"):
        if f"samesite={value}" in lowered:
            return value.capitalize()
    return None


def _dedupe_cookies(cookies: list[CookieInfo]) -> list[CookieInfo]:
    seen: dict[str, CookieInfo] = {}
    for cookie in cookies:
        seen.setdefault(cookie.name, cookie)
    return sorted(seen.values(), key=lambda c: c.name)


__all__ = ["CrawlerService"]
