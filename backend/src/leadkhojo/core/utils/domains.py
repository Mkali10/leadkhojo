"""Domain and URL canonicalization.

Deduplication depends entirely on this being right. "acme.com",
"www.acme.com", "https://acme.com/about", and "ACME.COM." must all collapse to
the same key — and "acme.co.uk" must not collapse to "co.uk", which is why we
use a public-suffix list rather than splitting on dots.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse, urlunparse

import tldextract

from leadkhojo.core.types import Domain, Url

# Bundled snapshot of the public suffix list. suffix_list_urls=() disables the
# network fetch: a crawler that phones home on import is a crawler that fails
# in an air-gapped CI run.
_extract = tldextract.TLDExtract(suffix_list_urls=())


def canonical_domain(value: str) -> Domain | None:
    """Reduce any URL or hostname to its registrable domain.

    >>> canonical_domain("https://www.acme.co.uk/contact?x=1")
    'acme.co.uk'
    >>> canonical_domain("not a domain")
    None
    """
    if not value or not value.strip():
        return None

    candidate = value.strip().lower()
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    try:
        host = urlparse(candidate).hostname
    except ValueError:
        return None
    if not host:
        return None

    host = host.rstrip(".")
    parts = _extract(host)
    if not parts.domain or not parts.suffix:
        return None

    return Domain(f"{parts.domain}.{parts.suffix}")


def normalize_url(value: str) -> Url | None:
    """Produce a fetchable absolute URL, defaulting to https."""
    if not value or not value.strip():
        return None

    candidate = value.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None

    # Drop fragments; they are never sent to the server anyway.
    return Url(urlunparse(parsed._replace(fragment="")))


def same_registrable_domain(a: str, b: str) -> bool:
    """True when two URLs belong to the same site (subdomains included)."""
    da, db = canonical_domain(a), canonical_domain(b)
    return da is not None and da == db


def join_url(base: str, href: str) -> Url | None:
    """Resolve a possibly-relative href against a base URL."""
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
        return None
    try:
        return normalize_url(urljoin(base, href))
    except ValueError:
        return None


def url_path(value: str) -> str:
    """The path component, always starting with '/'."""
    try:
        path = urlparse(value).path or "/"
    except ValueError:
        return "/"
    return path if path.startswith("/") else f"/{path}"


def hostname_of(value: str) -> str | None:
    try:
        return urlparse(value).hostname
    except ValueError:
        return None
