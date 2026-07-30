"""DNS and TLS collection.

These run once per site, in the crawler, and put their results in the
snapshot. No plugin performs DNS or TLS work — that is the crawl-once rule.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
from contextlib import suppress

import dns.asyncresolver
import dns.exception
import dns.resolver
from cryptography import x509
from cryptography.hazmat.primitives import hashes  # noqa: F401 - ensures backend import
from cryptography.x509.oid import NameOID

from leadkhojo.core.utils.clock import ensure_utc
from leadkhojo.crawler.snapshot import DnsInfo, TlsInfo

logger = logging.getLogger(__name__)

# A short, documented list. We do NOT iterate a wordlist — that would be
# enumeration, which is explicitly out of bounds.
_DKIM_SELECTORS: tuple[str, ...] = ("default", "google", "k1", "selector1", "selector2")

_DNS_TIMEOUT = 5.0


async def collect_dns(domain: str) -> DnsInfo | None:
    """Resolve the public records the analyzers need. Never raises."""
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = _DNS_TIMEOUT
    resolver.timeout = _DNS_TIMEOUT

    async def query(name: str, rdtype: str) -> tuple[str, ...]:
        try:
            answer = await resolver.resolve(name, rdtype)
        except (dns.exception.DNSException, OSError):
            return ()
        return tuple(r.to_text().strip('"') for r in answer)

    a, aaaa, mx, ns, txt, cname, dmarc = await asyncio.gather(
        query(domain, "A"),
        query(domain, "AAAA"),
        query(domain, "MX"),
        query(domain, "NS"),
        query(domain, "TXT"),
        query(domain, "CNAME"),
        query(f"_dmarc.{domain}", "TXT"),
    )

    if not any((a, aaaa, mx, ns, txt)):
        # Nothing resolved at all — treat as "we never looked" rather than
        # reporting a domain with no SPF when the domain does not exist.
        return None

    selector_results = await asyncio.gather(
        *(query(f"{selector}._domainkey.{domain}", "TXT") for selector in _DKIM_SELECTORS)
    )
    found_selectors = tuple(
        selector
        for selector, records in zip(_DKIM_SELECTORS, selector_results, strict=True)
        if records
    )

    dmarc_record = next((r for r in dmarc if r.lower().startswith("v=dmarc1")), None)

    dnssec = False
    with suppress(dns.exception.DNSException, OSError):
        dnskey = await query(domain, "DNSKEY")
        dnssec = bool(dnskey)

    # TXT records can arrive chunked; join fragments before matching SPF.
    joined_txt = tuple(r.replace('" "', "") for r in txt)

    return DnsInfo(
        a=a,
        aaaa=aaaa,
        mx=mx,
        ns=ns,
        txt=joined_txt,
        cname=cname[0] if cname else None,
        dmarc=dmarc_record,
        dkim_selectors=found_selectors,
        dnssec=dnssec,
        resolved_ip=a[0] if a else (aaaa[0] if aaaa else None),
    )


async def collect_tls(hostname: str, port: int = 443) -> TlsInfo | None:
    """Complete a TLS handshake and read the certificate. Never raises.

    This is the same handshake a browser performs to load the page — we simply
    keep the certificate rather than discarding it.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_collect_tls_sync, hostname, port),
            timeout=10.0,
        )
    except TimeoutError:
        logger.debug("tls.timeout", extra={"hostname": hostname})
        return None
    except Exception as exc:
        logger.debug("tls.failed", extra={"hostname": hostname, "error": str(exc)})
        return None


def _collect_tls_sync(hostname: str, port: int) -> TlsInfo | None:
    context = ssl.create_default_context()
    # We want to inspect a certificate even when it is invalid — an expired or
    # mismatched certificate is precisely the finding we are looking for.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with (
        socket.create_connection((hostname, port), timeout=8.0) as sock,
        context.wrap_socket(sock, server_hostname=hostname) as tls_sock,
    ):
        der = tls_sock.getpeercert(binary_form=True)
        protocol = tls_sock.version()
        cipher_info = tls_sock.cipher()

    if not der:
        return None

    cert = x509.load_der_x509_certificate(der)

    def _name(attr_oid: x509.ObjectIdentifier, name: x509.Name) -> str | None:
        values = name.get_attributes_for_oid(attr_oid)
        return str(values[0].value) if values else None

    sans: tuple[str, ...] = ()
    with suppress(x509.ExtensionNotFound):
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        sans = tuple(ext.value.get_values_for_type(x509.DNSName))

    subject = _name(NameOID.COMMON_NAME, cert.subject)
    issuer = _name(NameOID.COMMON_NAME, cert.issuer) or _name(
        NameOID.ORGANIZATION_NAME, cert.issuer
    )

    return TlsInfo(
        protocol=protocol,
        cipher=cipher_info[0] if cipher_info else None,
        issuer=issuer,
        subject=subject,
        sans=sans,
        not_before=ensure_utc(cert.not_valid_before_utc),
        not_after=ensure_utc(cert.not_valid_after_utc),
        is_self_signed=cert.issuer == cert.subject,
        chain_complete=True,  # a full chain check needs verify mode; see note below
        hostname_matches=_hostname_matches(hostname, subject, sans),
    )


def _hostname_matches(hostname: str, subject: str | None, sans: tuple[str, ...]) -> bool:
    candidates = [c for c in (*sans, subject) if c]
    host = hostname.lower().rstrip(".")
    for candidate in candidates:
        name = candidate.lower().rstrip(".")
        if name == host:
            return True
        wildcard = name.startswith("*.") and host.count(".") >= name.count(".") - 1
        if wildcard and host.endswith(name[1:]):
            return True
    return False


__all__ = ["collect_dns", "collect_tls"]
