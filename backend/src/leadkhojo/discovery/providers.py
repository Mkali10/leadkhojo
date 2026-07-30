"""Business discovery.

CsvImportProvider is built first deliberately: it has zero external
dependencies, so the whole pipeline is testable and demonstrable on day one
without an API key or a billing decision.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from leadkhojo.core.errors import InvalidCsvError
from leadkhojo.core.types import Domain, Url
from leadkhojo.core.utils.domains import canonical_domain, normalize_url

MAX_ROWS = 500
MAX_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DiscoveryQuery:
    keyword: str | None = None
    location: str | None = None
    limit: int = 25


@dataclass(frozen=True, slots=True)
class DiscoveredBusiness:
    name: str
    website_url: Url | None
    domain: Domain | None
    address: str | None = None
    city: str | None = None
    country_code: str | None = None
    category: str | None = None
    phone: str | None = None
    source: str = "csv_import"
    source_external_id: str | None = None

    @property
    def has_website(self) -> bool:
        return self.website_url is not None and self.domain is not None


@dataclass(frozen=True, slots=True)
class RowError:
    row: int
    reason: str


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    businesses: tuple[DiscoveredBusiness, ...]
    errors: tuple[RowError, ...] = ()
    detected_columns: dict[str, str] | None = None


@runtime_checkable
class DiscoveryProvider(Protocol):
    id: str

    async def search(self, query: DiscoveryQuery) -> DiscoveryResult: ...


# -- column detection ------------------------------------------------------

_DOMAIN_HEADERS = ("domain", "website", "url", "site", "web", "website url", "web address")
_NAME_HEADERS = ("name", "company", "business", "business name", "company name", "title")
_CITY_HEADERS = ("city", "town", "locality")
_COUNTRY_HEADERS = ("country", "country_code", "cc")


def _detect(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {h.strip().lower(): h for h in headers}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    # Fall back to a substring match so "Company Website URL" still works.
    for header_lower, original in lowered.items():
        if any(candidate in header_lower for candidate in candidates):
            return original
    return None


class CsvImportProvider:
    """Reads a CSV of domains. No network, no API key, no cost."""

    id = "csv_import"

    def __init__(self, content: str | bytes) -> None:
        if isinstance(content, bytes):
            if len(content) > MAX_BYTES:
                raise InvalidCsvError(
                    f"File is {len(content) // 1024} KB; the limit is {MAX_BYTES // 1024} KB.",
                    meta={"bytes": len(content), "limit": MAX_BYTES},
                )
            content = content.decode("utf-8-sig", errors="replace")
        self._content = content

    @classmethod
    def from_path(cls, path: Path) -> CsvImportProvider:
        return cls(path.read_bytes())

    async def search(self, query: DiscoveryQuery) -> DiscoveryResult:
        return self.parse(limit=query.limit)

    def parse(self, *, limit: int = MAX_ROWS) -> DiscoveryResult:
        stream = io.StringIO(self._content)
        try:
            sample = self._content[:4096]
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel  # type: ignore[assignment]

        reader = csv.DictReader(stream, dialect=dialect)
        headers = [h for h in (reader.fieldnames or []) if h]
        if not headers:
            raise InvalidCsvError("The file has no header row.")

        domain_col = _detect(headers, _DOMAIN_HEADERS)
        if domain_col is None:
            raise InvalidCsvError(
                "No domain or website column found. Expected one of: "
                f"{', '.join(_DOMAIN_HEADERS)}.",
                meta={"headers_found": headers},
            )

        name_col = _detect(headers, _NAME_HEADERS)
        city_col = _detect(headers, _CITY_HEADERS)
        country_col = _detect(headers, _COUNTRY_HEADERS)

        businesses: list[DiscoveredBusiness] = []
        errors: list[RowError] = []
        seen: set[str] = set()

        for index, row in enumerate(reader, start=1):
            if len(businesses) >= min(limit, MAX_ROWS):
                break

            raw = (row.get(domain_col) or "").strip()
            if not raw:
                errors.append(RowError(row=index, reason="empty domain"))
                continue

            domain = canonical_domain(raw)
            url = normalize_url(raw)
            if domain is None or url is None:
                errors.append(RowError(row=index, reason=f"not a valid domain: {raw!r}"))
                continue

            if domain in seen:
                continue  # deduplication is silent, not an error
            seen.add(domain)

            businesses.append(
                DiscoveredBusiness(
                    name=(row.get(name_col) or "").strip() if name_col else domain,
                    website_url=url,
                    domain=domain,
                    city=(row.get(city_col) or "").strip() or None if city_col else None,
                    country_code=(
                        ((row.get(country_col) or "").strip()[:2].upper() or None)
                        if country_col
                        else None
                    ),
                    source=self.id,
                )
            )

        detected = {"domain": domain_col}
        if name_col:
            detected["name"] = name_col
        if city_col:
            detected["city"] = city_col

        return DiscoveryResult(
            businesses=tuple(businesses),
            errors=tuple(errors),
            detected_columns=detected,
        )


__all__ = [
    "CsvImportProvider",
    "DiscoveredBusiness",
    "DiscoveryProvider",
    "DiscoveryQuery",
    "DiscoveryResult",
    "RowError",
]
