"""Contact Extractor plugin tests.

The rule this plugin exists to enforce:

    We never construct a contact that does not literally appear on a
    fetched page.

A business with no discoverable contact is a CORRECT result. Reporting
"no contact found" is honest; reporting a guess invents personal data and
presents it as observed fact.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from leadkhojo.plugins.base import PluginContext
from leadkhojo.plugins.builtin.contacts_plugin import ContactsPlugin
from tests.conftest import make_page, make_snapshot


def _run(html: str, now: datetime, url: str = "https://acme.com/") -> dict:
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(url=url, pages=(make_page(url, html=html),)), now=now
    )
    return dict(ContactsPlugin().run(ctx).artifacts)


def _emails(artifacts: dict) -> set[str]:
    return {c["value"] for c in artifacts["contacts"] if c["kind"] == "email"}


# ---------------------------------------------------------------- the core rule


def test_no_contact_found_produces_nothing_not_a_guess(now: datetime) -> None:
    """The single most important test in this module.

    We must NOT fall back to info@{domain}. That address may not exist, and
    inventing it puts a fabricated contact in an export the user will act on.
    """
    artifacts = _run("<html><body>We are a company. No contact here.</body></html>", now)

    assert artifacts["primary_email"] is None
    assert artifacts["contact_count"] == 0
    assert "info@acme.com" not in _emails(artifacts)


def test_every_contact_carries_the_url_it_was_found_on(now: datetime) -> None:
    """Provenance is what makes a contact defensible — and a synthesised
    address has no source URL to record."""
    artifacts = _run('<a href="mailto:info@acme.com">Email</a>', now)

    contacts = artifacts["contacts"]
    assert contacts
    for contact in contacts:
        assert contact["source_url"] == "https://acme.com/"


# ---------------------------------------------------------------- extraction


def test_mailto_links_are_extracted(now: datetime) -> None:
    artifacts = _run('<a href="mailto:info@acme.com?subject=Hi">Email us</a>', now)
    assert _emails(artifacts) == {"info@acme.com"}


def test_plain_text_addresses_are_extracted(now: datetime) -> None:
    artifacts = _run("<p>Reach us at sales@acme.com any time.</p>", now)
    assert _emails(artifacts) == {"sales@acme.com"}


def test_addresses_are_categorised_by_role(now: datetime) -> None:
    html = """
      <a href="mailto:info@acme.com">General</a>
      <a href="mailto:sales@acme.com">Sales</a>
      <a href="mailto:support@acme.com">Support</a>
      <a href="mailto:careers@acme.com">Jobs</a>
    """
    artifacts = _run(html, now)
    by_value = {c["value"]: c["category"] for c in artifacts["contacts"] if c["kind"] == "email"}

    assert by_value["info@acme.com"] == "general"
    assert by_value["sales@acme.com"] == "sales"
    assert by_value["support@acme.com"] == "support"
    assert by_value["careers@acme.com"] == "careers"


def test_the_most_useful_address_becomes_primary(now: datetime) -> None:
    """A general enquiries address outranks careers for sales outreach."""
    html = """
      <a href="mailto:careers@acme.com">Jobs</a>
      <a href="mailto:info@acme.com">General</a>
    """
    assert _run(html, now)["primary_email"] == "info@acme.com"


def test_phone_numbers_are_normalised_to_e164(now: datetime) -> None:
    artifacts = _run('<a href="tel:+1 512-555-0142">Call</a>', now)
    phones = [c["value"] for c in artifacts["contacts"] if c["kind"] == "phone"]
    assert phones == ["+15125550142"]


def test_social_profiles_are_extracted(now: datetime) -> None:
    html = """
      <a href="https://linkedin.com/company/acme">LinkedIn</a>
      <a href="https://facebook.com/acmecorp">Facebook</a>
      <a href="https://twitter.com/acme">Twitter</a>
    """
    artifacts = _run(html, now)
    categories = {c["category"] for c in artifacts["contacts"] if c["kind"] == "social"}
    assert {"linkedin", "facebook", "twitter"} <= categories


def test_share_buttons_are_not_mistaken_for_profiles(now: datetime) -> None:
    html = '<a href="https://facebook.com/sharer/sharer.php?u=x">Share</a>'
    artifacts = _run(html, now)
    assert not [c for c in artifacts["contacts"] if c["kind"] == "social"]


def test_contact_forms_are_detected(now: datetime) -> None:
    html = """
      <form action="/submit">
        <input type="email" name="email">
        <textarea name="message"></textarea>
      </form>
    """
    artifacts = _run(html, now)
    forms = [c for c in artifacts["contacts"] if c["kind"] == "form"]
    assert len(forms) == 1


def test_schema_org_address_is_preferred(now: datetime) -> None:
    html = """
      <div itemtype="https://schema.org/PostalAddress">
        1200 Congress Ave, Austin, TX 78701
      </div>
    """
    artifacts = _run(html, now)
    addresses = [c["value"] for c in artifacts["contacts"] if c["kind"] == "address"]
    assert addresses
    assert "Congress Ave" in addresses[0]


# ---------------------------------------------------------------- filtering


def test_personal_name_addresses_are_rejected(now: datetime) -> None:
    """A named individual's address is personal data. Role addresses only."""
    artifacts = _run('<a href="mailto:john.smith@acme.com">John</a>', now)
    assert not _emails(artifacts)


def test_freemail_addresses_are_rejected(now: datetime) -> None:
    """A gmail address on a company site is somebody's personal mailbox."""
    for provider in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com"):
        artifacts = _run(f'<a href="mailto:contact@{provider}">Mail</a>', now)
        assert not _emails(artifacts), f"{provider} should be rejected"


def test_third_party_domains_are_rejected(now: datetime) -> None:
    """Found in the wild on djangoproject.com: django@fosstodon.org, a
    Mastodon handle rendered as an email. It passes every other filter — a
    role-looking local part on a non-freemail domain — and was exported as
    the primary contact until this rule was added."""
    artifacts = _run('<a href="mailto:acme@fosstodon.org">Follow</a>', now)
    assert not _emails(artifacts)


def test_a_corporate_domain_variant_is_accepted(now: datetime) -> None:
    """acme.co.uk publishing acme.com addresses is legitimate."""
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(
            domain="acme.co.uk",
            url="https://acme.co.uk/",
            pages=(
                make_page(
                    "https://acme.co.uk/",
                    html='<a href="mailto:info@acme.com">Mail</a>',
                ),
            ),
        ),
        now=now,
    )
    artifacts = dict(ContactsPlugin().run(ctx).artifacts)
    assert _emails(artifacts) == {"info@acme.com"}


def test_placeholder_domains_are_rejected(now: datetime) -> None:
    for placeholder in ("example.com", "yourcompany.com", "domain.com"):
        artifacts = _run(f'<a href="mailto:info@{placeholder}">Mail</a>', now)
        assert not _emails(artifacts), f"{placeholder} should be rejected"


def test_asset_filenames_matching_the_email_shape_are_rejected(now: datetime) -> None:
    artifacts = _run('<img src="sprite@2x.png"><link href="icons@acme.svg">', now)
    assert not _emails(artifacts)


def test_addresses_are_deduplicated_case_insensitively(now: datetime) -> None:
    html = """
      <a href="mailto:Info@Acme.com">One</a>
      <a href="mailto:info@acme.com">Two</a>
      <p>INFO@ACME.COM</p>
    """
    assert _emails(_run(html, now)) == {"info@acme.com"}


# ---------------------------------------------------------------- robustness


@pytest.mark.parametrize(
    "html",
    ["", "<html>", "<html><body><a href='mailto:'></a></body></html>", "not html at all"],
)
def test_malformed_input_never_raises(html: str, now: datetime) -> None:
    artifacts = _run(html, now)
    assert artifacts["contact_count"] >= 0


def test_a_snapshot_with_no_pages_is_handled(now: datetime) -> None:
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=()), now=now)
    result = ContactsPlugin().run(ctx)
    assert result.artifacts["contact_count"] == 0
