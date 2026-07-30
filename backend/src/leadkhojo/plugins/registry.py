"""Explicit plugin registration.

No auto-discovery (ADR-14). An explicit list is debuggable, has no import
side effects, and makes the enabled plugin set obvious to anyone reading the
file. Third-party plugin discovery is a real feature — for later, not for v1.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from leadkhojo.opportunities.engine import OpportunityEngine, load_opportunity_rules
from leadkhojo.opportunities.rewriter import NullRewriter, OpportunityRewriter
from leadkhojo.plugins.base import Plugin
from leadkhojo.plugins.builtin.cms_plugin import CmsPlugin
from leadkhojo.plugins.builtin.contacts_plugin import ContactsPlugin
from leadkhojo.plugins.builtin.dns_plugin import DnsPlugin
from leadkhojo.plugins.builtin.headers_plugin import HeadersPlugin
from leadkhojo.plugins.builtin.opportunities_plugin import OpportunitiesPlugin
from leadkhojo.plugins.builtin.performance_plugin import PerformancePlugin
from leadkhojo.plugins.builtin.ssl_plugin import SslPlugin
from leadkhojo.plugins.builtin.technologies_plugin import TechnologiesPlugin
from leadkhojo.plugins.engine import PluginEngine
from leadkhojo.plugins.rules import load_rule_packs


def build_plugins(
    rules_dir: Path,
    *,
    rewriter: OpportunityRewriter | None = None,
) -> tuple[Plugin, ...]:
    """Construct the built-in plugin set.

    Rule packs are loaded here, at startup. A malformed pack fails the boot
    loudly rather than surfacing on someone's fortieth site.
    """
    packs = load_rule_packs(rules_dir)
    opportunity_rules = load_opportunity_rules(rules_dir)

    return (
        SslPlugin(),
        DnsPlugin(),
        HeadersPlugin(),
        TechnologiesPlugin(packs),
        CmsPlugin(),
        PerformancePlugin(),
        ContactsPlugin(),
        OpportunitiesPlugin(
            OpportunityEngine(opportunity_rules),
            rewriter or NullRewriter(),
        ),
    )


def build_engine(
    rules_dir: Path,
    *,
    disabled: Iterable[str] = (),
    rewriter: OpportunityRewriter | None = None,
) -> PluginEngine:
    return PluginEngine(build_plugins(rules_dir, rewriter=rewriter), disabled=disabled)


__all__ = ["build_engine", "build_plugins"]
