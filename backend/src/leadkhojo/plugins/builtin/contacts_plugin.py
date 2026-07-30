"""Contact extraction — business contact details, from the company's own pages.

THE RULE THIS FILE EXISTS TO ENFORCE:

    We never construct a contact that does not literally appear on a fetched
    page. No `info@{domain}` fallback. No `first.last@` pattern inference. No
    permutation. A business with no discoverable contact is a CORRECT result.

Reporting "no contact found" is honest. Reporting a guess is inventing
personal data and presenting it as observed fact. Every extracted value
carries the URL it was found on — a value with no source URL cannot exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar

import phonenumbers
from bs4 import BeautifulSoup

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import ContactCategory, ContactKind
from leadkhojo.core.utils.domains import canonical_domain, join_url
from leadkhojo.plugins.base import BasePlugin, PluginContext, PluginKind, PluginMeta, PluginResult

PLUGIN_ID = "contacts"
CATEGORY = "contacts"

_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

# Domains that appear in markup but are never a business contact.
_PLACEHOLDER_DOMAINS: frozenset[str] = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "domain.com",
        "yourdomain.com",
        "yourcompany.com",
        "email.com",
        "test.com",
        "sentry.io",
        "wixpress.com",
        "godaddy.com",
        "squarespace.com",
        "w3.org",
        "schema.org",
        "sentry-cdn.com",
        "googleapis.com",
        "gstatic.com",
        "cloudflare.com",
        "jquery.com",
    }
)

# Free-mail providers: a personal address, not a business contact.
_FREEMAIL_DOMAINS: frozenset[str] = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "aol.com",
        "icloud.com",
        "me.com",
        "protonmail.com",
        "gmx.com",
        "mail.com",
        "yandex.com",
        "zoho.com",
    }
)

_ROLE_PREFIXES: dict[str, ContactCategory] = {
    "info": ContactCategory.GENERAL,
    "hello": ContactCategory.GENERAL,
    "contact": ContactCategory.GENERAL,
    "enquiries": ContactCategory.GENERAL,
    "inquiries": ContactCategory.GENERAL,
    "office": ContactCategory.GENERAL,
    "admin": ContactCategory.GENERAL,
    "mail": ContactCategory.GENERAL,
    "sales": ContactCategory.SALES,
    "business": ContactCategory.SALES,
    "partnerships": ContactCategory.SALES,
    "support": ContactCategory.SUPPORT,
    "help": ContactCategory.SUPPORT,
    "service": ContactCategory.SUPPORT,
    "helpdesk": ContactCategory.SUPPORT,
    "careers": ContactCategory.CAREERS,
    "jobs": ContactCategory.CAREERS,
    "hr": ContactCategory.CAREERS,
    "recruitment": ContactCategory.CAREERS,
    "security": ContactCategory.SECURITY,
    "abuse": ContactCategory.SECURITY,
    "privacy": ContactCategory.SECURITY,
    "billing": ContactCategory.BILLING,
    "accounts": ContactCategory.BILLING,
    "invoices": ContactCategory.BILLING,
}

# Ranking: which address should be the exported "primary contact".
_CATEGORY_RANK: dict[ContactCategory, int] = {
    ContactCategory.GENERAL: 10,
    ContactCategory.SALES: 20,
    ContactCategory.SUPPORT: 30,
    ContactCategory.BILLING: 50,
    ContactCategory.SECURITY: 60,
    ContactCategory.CAREERS: 70,
    ContactCategory.OTHER: 90,
}

_SOCIAL_PATTERNS: tuple[tuple[ContactCategory, re.Pattern[str]], ...] = (
    (ContactCategory.LINKEDIN, re.compile(r"linkedin\.com/(?:company|in)/[\w\-.%]+", re.I)),
    (ContactCategory.FACEBOOK, re.compile(r"facebook\.com/[\w\-.%]+", re.I)),
    (ContactCategory.TWITTER, re.compile(r"(?:twitter\.com|x\.com)/[\w\-.%]+", re.I)),
    (ContactCategory.INSTAGRAM, re.compile(r"instagram\.com/[\w\-.%]+", re.I)),
    (ContactCategory.YOUTUBE, re.compile(r"youtube\.com/(?:c|channel|user|@)[\w\-.%/]+", re.I)),
)

_SOCIAL_NOISE = re.compile(
    r"/(?:sharer|share|intent|dialog|plugins|tr\?|home\?|login|privacy|policies)", re.I
)


@dataclass(frozen=True, slots=True)
class ExtractedContact:
    kind: ContactKind
    category: ContactCategory
    value: str
    normalized_value: str
    source_url: str  # never optional — see module docstring
    rank: int = 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "category": self.category.value,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "source_url": self.source_url,
            "rank": self.rank,
        }


class ContactsPlugin(BasePlugin):
    meta: ClassVar[PluginMeta] = PluginMeta(
        id=PLUGIN_ID,
        name="Contact Extraction",
        version="1.0.0",
        kind=PluginKind.ANALYZER,
        description="Business emails, phones, address, social profiles and contact forms.",
        provides=("contacts", "primary_email", "primary_phone", "contact_count"),
        budget_ms=900,
    )

    def run(self, ctx: PluginContext) -> PluginResult:
        snap = ctx.snapshot
        if not snap.pages:
            return self._result(
                (
                    Finding.informational(
                        "CONTACT-01",
                        plugin_id=PLUGIN_ID,
                        category=CATEGORY,
                        title="No pages available for contact extraction",
                    ),
                ),
                {"contacts": [], "primary_email": None, "primary_phone": None, "contact_count": 0},
            )

        site_domain = canonical_domain(snap.final_url or snap.requested_url) or snap.domain
        contacts: list[ExtractedContact] = []

        for page in snap.pages:
            if not page.html:
                continue
            soup = BeautifulSoup(page.html, "lxml")
            contacts.extend(self._emails(soup, page.html, page.final_url, site_domain))
            contacts.extend(self._phones(soup, page.final_url, snap))
            contacts.extend(self._socials(page.html, page.final_url))
            contacts.extend(self._forms(soup, page.final_url))
            address = self._address(soup, page.final_url)
            if address:
                contacts.append(address)

        contacts = _dedupe(contacts)

        emails = sorted((c for c in contacts if c.kind is ContactKind.EMAIL), key=lambda c: c.rank)
        phones = [c for c in contacts if c.kind is ContactKind.PHONE]

        findings = [self._summary_finding(contacts, emails, phones)]

        return self._result(
            tuple(findings),
            {
                "contacts": [c.to_dict() for c in contacts],
                "primary_email": emails[0].value if emails else None,
                "primary_phone": phones[0].value if phones else None,
                "contact_count": len(contacts),
            },
        )

    # -- extraction --------------------------------------------------------

    def _emails(
        self, soup: BeautifulSoup, html: str, source_url: str, site_domain: str
    ) -> list[ExtractedContact]:
        found: dict[str, ExtractedContact] = {}

        candidates: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if href.lower().startswith("mailto:"):
                address = href[7:].split("?")[0].strip()
                if address:
                    candidates.append(address)

        candidates.extend(match.group(0) for match in _EMAIL_RE.finditer(html))

        for raw in candidates:
            address = raw.strip().strip(".,;:").lower()
            if not _EMAIL_RE.fullmatch(address):
                continue
            if not self._is_business_email(address, site_domain):
                continue
            if not self._belongs_to_business(address, site_domain):
                continue
            local = address.partition("@")[0]
            category = self._categorize(local)
            rank = _CATEGORY_RANK.get(category, 90)
            found.setdefault(
                address,
                ExtractedContact(
                    kind=ContactKind.EMAIL,
                    category=category,
                    value=address,
                    normalized_value=address,
                    source_url=source_url,
                    rank=rank,
                ),
            )

        return list(found.values())

    @staticmethod
    def _is_business_email(address: str, site_domain: str) -> bool:
        local, _, domain = address.partition("@")
        domain = domain.lower()

        if not local or not domain:
            return False

        registrable = canonical_domain(domain)
        if registrable is None:
            return False
        if registrable in _PLACEHOLDER_DOMAINS or domain in _PLACEHOLDER_DOMAINS:
            return False
        if registrable in _FREEMAIL_DOMAINS:
            # A personal mailbox, not a business contact.
            return False

        # Filenames that happen to match the email shape (sprite@2x.png etc.)
        if re.search(r"\.(png|jpe?g|gif|svg|webp|css|js|woff2?)$", address):
            return False

        # A person's name is personal data; we collect role addresses only.
        # "john.smith@" and "j.smith@" are people. "sales.eu@" is a role.
        head = re.split(r"[._\-+]", local)[0].lower()
        looks_personal = re.fullmatch(r"[a-z]{1,20}[._\-][a-z]{2,20}", local) is not None
        return not (looks_personal and head not in _ROLE_PREFIXES)

    @staticmethod
    def _belongs_to_business(address: str, site_domain: str) -> bool:
        """Is this address actually the business's own?

        Found in the wild on djangoproject.com: `django@fosstodon.org`, a
        Mastodon handle rendered as an email. It passes every other filter —
        a role-looking local part on a non-freemail domain — and would have
        been exported as the primary contact.

        A business contact belongs to the business. We accept the site's own
        registrable domain, or one sharing its brand token (example.co.uk
        publishing example.com addresses), and nothing else.
        """
        _, _, domain = address.partition("@")
        registrable = canonical_domain(domain)
        if registrable is None:
            return False
        if registrable == site_domain:
            return True

        def brand(value: str) -> str:
            return value.split(".")[0].lower()

        return brand(registrable) == brand(site_domain)

    @staticmethod
    def _categorize(local: str) -> ContactCategory:
        head = re.split(r"[._\-+]", local)[0].lower()
        return _ROLE_PREFIXES.get(head, ContactCategory.OTHER)

    def _phones(
        self, soup: BeautifulSoup, source_url: str, snapshot: Any
    ) -> list[ExtractedContact]:
        region = None
        found: dict[str, ExtractedContact] = {}

        raw_numbers: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            if href.lower().startswith("tel:"):
                raw_numbers.append(href[4:].strip())

        text = soup.get_text(" ", strip=True)[:20000]
        for match in phonenumbers.PhoneNumberMatcher(text, region):
            raw_numbers.append(
                phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
            )

        for raw in raw_numbers:
            normalized = self._normalize_phone(raw, region)
            if normalized is None:
                continue
            found.setdefault(
                normalized,
                ExtractedContact(
                    kind=ContactKind.PHONE,
                    category=ContactCategory.GENERAL,
                    value=normalized,
                    normalized_value=normalized,
                    source_url=source_url,
                    rank=10,
                ),
            )

        return list(found.values())

    @staticmethod
    def _normalize_phone(raw: str, region: str | None) -> str | None:
        cleaned = re.sub(r"[^\d+]", "", raw)
        if len(re.sub(r"\D", "", cleaned)) < 7:
            return None
        try:
            parsed = phonenumbers.parse(cleaned, region)
        except phonenumbers.NumberParseException:
            return None
        if not phonenumbers.is_valid_number(parsed):
            return None
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

    def _socials(self, html: str, source_url: str) -> list[ExtractedContact]:
        found: dict[str, ExtractedContact] = {}
        for category, pattern in _SOCIAL_PATTERNS:
            for match in pattern.finditer(html):
                url = match.group(0)
                if _SOCIAL_NOISE.search(url):
                    continue
                normalized = url.lower().rstrip("/")
                found.setdefault(
                    normalized,
                    ExtractedContact(
                        kind=ContactKind.SOCIAL,
                        category=category,
                        value=f"https://{url}" if not url.startswith("http") else url,
                        normalized_value=normalized,
                        source_url=source_url,
                        rank=40,
                    ),
                )
        return list(found.values())

    def _forms(self, soup: BeautifulSoup, source_url: str) -> list[ExtractedContact]:
        for form in soup.find_all("form"):
            inputs = form.find_all(["input", "textarea"])
            types = {str(i.get("type", "text")).lower() for i in inputs}
            names = " ".join(str(i.get("name", "")).lower() for i in inputs)
            looks_like_contact = "email" in types or "email" in names or "message" in names
            if looks_like_contact and len(inputs) >= 2:
                action = str(form.get("action") or "")
                target = join_url(source_url, action) if action else source_url
                return [
                    ExtractedContact(
                        kind=ContactKind.FORM,
                        category=ContactCategory.GENERAL,
                        value=str(target or source_url),
                        normalized_value=str(target or source_url).lower(),
                        source_url=source_url,
                        rank=60,
                    )
                ]
        return []

    def _address(self, soup: BeautifulSoup, source_url: str) -> ExtractedContact | None:
        # schema.org PostalAddress is authoritative when present.
        node = soup.find(attrs={"itemtype": re.compile(r"PostalAddress", re.I)})
        if node is not None:
            text = " ".join(node.get_text(" ", strip=True).split())
            if 10 <= len(text) <= 300:
                return ExtractedContact(
                    kind=ContactKind.ADDRESS,
                    category=ContactCategory.GENERAL,
                    value=text,
                    normalized_value=text.lower(),
                    source_url=source_url,
                    rank=30,
                )

        tag = soup.find("address")
        if tag is not None:
            text = " ".join(tag.get_text(" ", strip=True).split())
            if 10 <= len(text) <= 300:
                return ExtractedContact(
                    kind=ContactKind.ADDRESS,
                    category=ContactCategory.GENERAL,
                    value=text,
                    normalized_value=text.lower(),
                    source_url=source_url,
                    rank=35,
                )
        return None

    # -- reporting ---------------------------------------------------------

    def _summary_finding(
        self,
        contacts: list[ExtractedContact],
        emails: list[ExtractedContact],
        phones: list[ExtractedContact],
    ) -> Finding:
        if not contacts:
            return Finding.informational(
                "CONTACT-01",
                plugin_id=PLUGIN_ID,
                category=CATEGORY,
                title="No business contact details published",
                description=(
                    "No business email, phone number or contact form was found on the "
                    "pages we fetched. This is a real result, not a failure — we do "
                    "not guess addresses."
                ),
                evidence={"contacts_found": 0},
            )

        return Finding.informational(
            "CONTACT-01",
            plugin_id=PLUGIN_ID,
            category=CATEGORY,
            title=f"{len(contacts)} contact details found",
            evidence={
                "emails": len(emails),
                "phones": len(phones),
                "socials": sum(1 for c in contacts if c.kind is ContactKind.SOCIAL),
                "has_form": any(c.kind is ContactKind.FORM for c in contacts),
                "primary_email": emails[0].value if emails else None,
                "sources": sorted({c.source_url for c in contacts})[:5],
            },
        )


def _dedupe(contacts: list[ExtractedContact]) -> list[ExtractedContact]:
    """One entry per (kind, normalized value); keep the best-ranked source."""
    best: dict[tuple[ContactKind, str], ExtractedContact] = {}
    for contact in contacts:
        key = (contact.kind, contact.normalized_value)
        current = best.get(key)
        if current is None or contact.rank < current.rank:
            best[key] = contact
    return sorted(best.values(), key=lambda c: (c.kind.value, c.rank, c.normalized_value))


__all__ = ["PLUGIN_ID", "ContactsPlugin", "ExtractedContact"]
