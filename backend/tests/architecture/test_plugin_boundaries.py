"""Architecture guards.

These are the most important tests in the repository. Each enforces a rule
that is load-bearing for the product's correctness or its legal position.
An architecture that is only a convention is not an architecture.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "leadkhojo"
PLUGINS = SRC / "plugins"
BUILTIN = PLUGINS / "builtin"

# Anything that could reach the network, the filesystem, or a subprocess.
FORBIDDEN_IN_PLUGINS = {
    "httpx",
    "requests",
    "aiohttp",
    "urllib",
    "urllib3",
    "socket",
    "ssl",
    "dns",
    "subprocess",
    "asyncio",
}

# No AI/model client may be reachable from analysis code.
FORBIDDEN_AI_MODULES = {"anthropic", "openai", "google", "cohere", "litellm", "transformers"}


def _python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in str(p))


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


# ---------------------------------------------------------------- R13: no I/O


def test_plugins_perform_no_io() -> None:
    """A plugin's world is its PluginContext. It receives data, never clients.

    This is what makes crawl-once/analyze-many structural rather than
    aspirational, and what keeps every plugin test offline and instant.
    """
    violations: list[str] = []

    for path in _python_files(PLUGINS):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(SRC)

        for root in _imported_roots(tree) & FORBIDDEN_IN_PLUGINS:
            violations.append(f"{relative} imports {root!r}")

        for node in ast.walk(tree):
            is_open_call = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
            )
            if is_open_call:
                violations.append(f"{relative} calls open()")

    assert not violations, (
        "Plugins must perform no I/O. If a plugin needs data, the CRAWLER must "
        "collect it into the snapshot.\n  " + "\n  ".join(violations)
    )


# ------------------------------------------------- R12: plugins never import each other


def test_plugins_never_import_each_other() -> None:
    """Cross-plugin data flows through declared depends_on, never an import.

    An imported dependency is invisible to the engine: it cannot be ordered,
    skipped, or stubbed, and the dependent is no longer testable in isolation.
    """
    plugin_modules = {p.stem for p in BUILTIN.glob("*_plugin.py")}
    violations: list[str] = []

    for path in BUILTIN.glob("*_plugin.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            if not module:
                continue
            leaf = module.split(".")[-1]
            if leaf in plugin_modules and leaf != path.stem:
                violations.append(f"{path.name} imports {leaf}")

    assert not violations, (
        "Plugins must not import one another. Declare depends_on and read the "
        "artifact through ctx.artifact().\n  " + "\n  ".join(violations)
    )


def test_engine_does_not_import_specific_plugins() -> None:
    """The core engine receives a registry. It knows nothing about SSL or DNS."""
    tree = ast.parse((PLUGINS / "engine.py").read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    leaked = {m for m in imported if "builtin" in m}
    assert not leaked, f"engine.py must not know about specific plugins: {leaked}"


# ---------------------------------------------------------------- R11: the AI boundary


def test_no_ai_client_reachable_from_analysis_code() -> None:
    """AI may never generate a finding, fact, number, date, or opportunity.

    The guarantee is structural: no model client is importable anywhere that
    produces analysis output.
    """
    roots = [PLUGINS, SRC / "opportunities" / "engine.py", SRC / "scoring"]
    violations: list[str] = []

    for root in roots:
        files = _python_files(root) if root.is_dir() else [root]
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for module in _imported_roots(tree) & FORBIDDEN_AI_MODULES:
                violations.append(f"{path.relative_to(SRC)} imports {module!r}")

    assert not violations, (
        "AI must not be reachable from code that produces findings or "
        "opportunities. The only permitted seam is opportunities/rewriter.py, "
        "which rephrases existing text.\n  " + "\n  ".join(violations)
    )


def test_rewriter_can_only_return_a_string() -> None:
    """The rewriter signature is the enforcement mechanism.

    Returning `str` means a rewriter is structurally incapable of creating an
    opportunity, changing urgency, or touching evidence.
    """
    from leadkhojo.opportunities.rewriter import NullRewriter, OpportunityRewriter

    annotations = OpportunityRewriter.rewrite.__annotations__
    assert annotations.get("return") is str or annotations.get("return") == "str", (
        "OpportunityRewriter.rewrite must return str, never an Opportunity."
    )
    assert isinstance(NullRewriter(), OpportunityRewriter)


def test_rewrite_cannot_overwrite_the_deterministic_description() -> None:
    from leadkhojo.core.types import OpportunityCategory, RuleId, Urgency
    from leadkhojo.opportunities.schemas import Opportunity

    original = Opportunity(
        rule_id=RuleId("ssl_renewal"),
        title="Certificate expires soon",
        category=OpportunityCategory.SECURITY,
        urgency=Urgency.CRITICAL,
        description="The certificate expires in 9 days.",
        pitch_angle="Lead with the date.",
        evidence={"days_remaining": 9},
        triggered_by=("TLS-04",),
    )
    rewritten = original.with_rewrite("Their certificate lapses in 9 days.")

    assert rewritten.description == original.description, (
        "A rewrite must never overwrite the deterministic description."
    )
    assert rewritten.description_ai == "Their certificate lapses in 9 days."
    assert rewritten.evidence == original.evidence
    assert rewritten.urgency is original.urgency


def test_rewrite_introducing_a_number_is_rejected() -> None:
    """The failure that actually matters: a hallucinated figure in an email."""
    from leadkhojo.core.types import OpportunityCategory, RuleId, Urgency
    from leadkhojo.opportunities.rewriter import apply_rewriter
    from leadkhojo.opportunities.schemas import Opportunity

    class HallucinatingRewriter:
        def rewrite(self, opportunity: Opportunity) -> str:
            return "The certificate expired 40 days ago and 3 domains are affected."

    opportunity = Opportunity(
        rule_id=RuleId("ssl_renewal"),
        title="Certificate expires soon",
        category=OpportunityCategory.SECURITY,
        urgency=Urgency.CRITICAL,
        description="The certificate expires in 9 days.",
        pitch_angle="Lead with the date.",
        evidence={"days_remaining": 9},
        triggered_by=("TLS-04",),
    )

    result = apply_rewriter(opportunity, HallucinatingRewriter())
    assert result.description_ai is None, "A rewrite inventing numbers must be rejected"
    assert result.display_description == opportunity.description


def test_a_failing_rewriter_never_breaks_the_pipeline() -> None:
    from leadkhojo.core.types import OpportunityCategory, RuleId, Urgency
    from leadkhojo.opportunities.rewriter import apply_rewriter
    from leadkhojo.opportunities.schemas import Opportunity

    class ExplodingRewriter:
        def rewrite(self, opportunity: Opportunity) -> str:
            raise RuntimeError("model unavailable")

    opportunity = Opportunity(
        rule_id=RuleId("x"),
        title="t",
        category=OpportunityCategory.SECURITY,
        urgency=Urgency.LOW,
        description="Deterministic text.",
        pitch_angle="p",
        evidence={"a": 1},
        triggered_by=("X-01",),
    )
    result = apply_rewriter(opportunity, ExplodingRewriter())
    assert result.display_description == "Deterministic text."


# ---------------------------------------------------------------- R4: no synthesis


def test_no_email_address_is_ever_synthesised() -> None:
    """We never construct a contact that is not literally on a fetched page.

    Guessing info@{domain} invents personal data and presents it as observed
    fact. A business with no discoverable contact is a correct result.
    """
    source = (BUILTIN / "contacts_plugin.py").read_text(encoding="utf-8")
    banned_patterns = ['f"info@', "f'info@", 'f"{local}@', "'@' + domain", '"@" + domain']
    found = [p for p in banned_patterns if p in source]
    assert not found, f"Contact synthesis detected: {found}"


def test_every_extracted_contact_carries_a_source_url() -> None:
    from leadkhojo.plugins.builtin.contacts_plugin import ExtractedContact

    fields = ExtractedContact.__dataclass_fields__
    assert "source_url" in fields
    assert (
        fields["source_url"].default is None
        or fields["source_url"].default.__class__ is not type(None)
        or True
    )
    # source_url has no default: it cannot be omitted at construction.
    import dataclasses

    assert fields["source_url"].default is dataclasses.MISSING, (
        "source_url must be required — a contact without provenance cannot exist."
    )


# ---------------------------------------------------------------- R2: passive only


def test_only_web_ports_are_permitted() -> None:
    """Connecting anywhere but 80/443 would make this a port scanner."""
    from leadkhojo.core.errors import CrawlError
    from leadkhojo.crawler.guards import ALLOWED_PORTS, assert_allowed_port

    assert frozenset({80, 443}) == ALLOWED_PORTS
    assert_allowed_port(80)
    assert_allowed_port(443)
    for port in (22, 21, 3306, 8080, 25, 3389):
        with pytest.raises(CrawlError):
            assert_allowed_port(port)


def test_private_addresses_are_refused() -> None:
    """SSRF guard: the highest-severity application risk in this product."""
    from leadkhojo.core.errors import CrawlError
    from leadkhojo.crawler.guards import assert_public_address, is_blocked_address

    blocked = [
        "127.0.0.1",
        "10.0.0.1",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",  # cloud metadata — the classic SSRF target
        "::1",
        "fc00::1",
        "0.0.0.0",
    ]
    for ip in blocked:
        assert is_blocked_address(ip), f"{ip} must be blocked"
        with pytest.raises(CrawlError):
            assert_public_address(ip)

    for ip in ("93.184.216.34", "8.8.8.8", "1.1.1.1"):
        assert not is_blocked_address(ip)
        assert_public_address(ip)


def test_no_override_exists_for_robots() -> None:
    """robots.txt is honoured with no escape hatch. There must be no flag."""
    source = (SRC / "crawler" / "service.py").read_text(encoding="utf-8")
    for escape_hatch in ("ignore_robots", "skip_robots", "force=True", "bypass_robots"):
        assert escape_hatch not in source, f"Found a robots override: {escape_hatch}"
