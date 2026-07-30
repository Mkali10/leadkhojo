"""SSRF protection.

This is the highest-severity application risk in the product: we take a
user-supplied URL and fetch it, which is the textbook SSRF setup.

The guard lives in the fetcher itself — not in a caller that could be
bypassed — and it runs AFTER DNS resolution and BEFORE connecting, then again
after every redirect. A redirect to http://169.254.169.254/ is the classic
bypass and the reason the post-redirect re-check exists.
"""

from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache

from leadkhojo.core.errors import CrawlError
from leadkhojo.core.utils.domains import hostname_of

_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",  # "this" network
        "10.0.0.0/8",  # RFC1918
        "100.64.0.0/10",  # carrier-grade NAT
        "127.0.0.0/8",  # loopback
        "169.254.0.0/16",  # link-local — cloud metadata lives here
        "172.16.0.0/12",  # RFC1918
        "192.0.0.0/24",  # IETF protocol assignments
        "192.168.0.0/16",  # RFC1918
        "198.18.0.0/15",  # benchmarking
        "224.0.0.0/4",  # multicast
        "240.0.0.0/4",  # reserved
        "255.255.255.255/32",
        "::1/128",  # loopback
        "fc00::/7",  # unique local
        "fe80::/10",  # link-local
        "ff00::/8",  # multicast
    )
)

# Ports we are permitted to speak to. Anything else would be a port scan.
ALLOWED_PORTS: frozenset[int] = frozenset({80, 443})


def is_blocked_address(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable: refuse rather than guess
    return any(address in network for network in _BLOCKED_NETWORKS)


def assert_public_address(ip: str, *, context: str = "") -> None:
    """Refuse to connect to a non-public address."""
    if is_blocked_address(ip):
        where = f" ({context})" if context else ""
        raise CrawlError(
            f"Refusing to fetch a non-public address: {ip}{where}",
            meta={"ip": ip, "context": context},
        )


def assert_allowed_port(port: int) -> None:
    """Enforce the passive-only boundary at the port level.

    Connecting to anything other than 80/443 would make this a port scanner.
    """
    if port not in ALLOWED_PORTS:
        raise CrawlError(
            f"Refusing to connect to port {port}. LeadKhojo speaks only to "
            f"{sorted(ALLOWED_PORTS)} — anything else would be active scanning.",
            meta={"port": port},
        )


@lru_cache(maxsize=2048)
def resolve_host(hostname: str) -> tuple[str, ...]:
    """Resolve a hostname to its addresses. Cached per process."""
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return ()
    return tuple(dict.fromkeys(info[4][0] for info in infos))


def assert_url_is_fetchable(url: str) -> str:
    """Validate a URL end to end before any connection is opened.

    Returns the resolved IP so the caller can record it without resolving
    twice (and without a TOCTOU window where the answer could change).
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise CrawlError(
            f"Refusing to fetch non-HTTP scheme: {parsed.scheme!r}",
            meta={"url": url},
        )

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    assert_allowed_port(port)

    hostname = hostname_of(url)
    if not hostname:
        raise CrawlError(f"URL has no hostname: {url}", meta={"url": url})

    addresses = resolve_host(hostname)
    if not addresses:
        raise CrawlError(
            f"Could not resolve {hostname}",
            meta={"hostname": hostname},
        )

    for ip in addresses:
        assert_public_address(ip, context=hostname)

    return addresses[0]


__all__ = [
    "ALLOWED_PORTS",
    "assert_allowed_port",
    "assert_public_address",
    "assert_url_is_fetchable",
    "is_blocked_address",
    "resolve_host",
]
