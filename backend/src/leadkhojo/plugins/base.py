"""The plugin contract.

A plugin's entire world is its PluginContext. It receives data — never a
client, a session, or a connection. This is what makes every plugin
independently testable and what keeps the crawl-once/analyze-many guarantee
structural rather than aspirational.

Rules enforced elsewhere by architecture tests:
  * plugins perform no I/O                      (test_no_io_in_plugins.py)
  * plugins never import one another            (test_plugin_isolation.py)
  * cross-plugin data flows via depends_on      (declared, not imported)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from leadkhojo.core.findings import Finding
from leadkhojo.core.types import PluginId

if TYPE_CHECKING:
    from leadkhojo.crawler.snapshot import SiteSnapshot
    from leadkhojo.opportunities.schemas import Opportunity


class PluginKind(StrEnum):
    ANALYZER = "analyzer"  # snapshot  -> findings + artifacts
    SYNTHESIZER = "synthesizer"  # findings  -> opportunities
    REPORTER = "reporter"  # everything -> bytes


@dataclass(frozen=True, slots=True)
class PluginMeta:
    id: str
    name: str
    version: str
    kind: PluginKind
    description: str = ""
    depends_on: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    budget_ms: int = 200

    def __post_init__(self) -> None:
        if not self.id or not self.id.replace("_", "").isalnum():
            raise ValueError(f"Plugin id must be alphanumeric/underscore: {self.id!r}")
        if self.id in self.depends_on:
            raise ValueError(f"Plugin {self.id!r} cannot depend on itself")


@dataclass(frozen=True, slots=True)
class PluginResult:
    """What a plugin produces.

    `artifacts` is how a plugin publishes structured data for dependents.
    A key here must be declared in meta.provides — the engine checks it, so a
    dependent can rely on the contract instead of hoping.
    """

    plugin_id: PluginId
    findings: tuple[Finding, ...] = ()
    artifacts: Mapping[str, Any] = field(default_factory=dict)
    opportunities: tuple[Opportunity, ...] = ()

    @classmethod
    def empty(cls, plugin_id: str) -> PluginResult:
        return cls(plugin_id=PluginId(plugin_id))


@dataclass(frozen=True, slots=True)
class PluginSettings:
    """Configuration a plugin may read. Deliberately tiny.

    A plugin that needs more configuration than this is usually a plugin that
    should be several plugins, or a rule pack.
    """

    max_pages_per_site: int = 8
    slow_ttfb_ms: int = 1500
    cert_expiry_warn_days: int = 30


class PluginContext:
    """Everything a plugin is allowed to see.

    Constructed by the engine for real runs, or by `for_testing` in tests. The
    two paths are identical, which is why a plugin test needs no engine.
    """

    __slots__ = ("_results", "now", "settings", "snapshot")

    def __init__(
        self,
        *,
        snapshot: SiteSnapshot,
        now: datetime,
        settings: PluginSettings | None = None,
        results: Mapping[str, PluginResult] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.now = now
        self.settings = settings or PluginSettings()
        self._results: dict[str, PluginResult] = dict(results or {})

    # -- reading dependency output -----------------------------------------

    def result(self, plugin_id: str) -> PluginResult | None:
        return self._results.get(plugin_id)

    def artifact(self, plugin_id: str, key: str, default: Any = None) -> Any:
        result = self._results.get(plugin_id)
        if result is None:
            return default
        return result.artifacts.get(key, default)

    def findings_from(self, plugin_id: str) -> tuple[Finding, ...]:
        result = self._results.get(plugin_id)
        return result.findings if result else ()

    def all_findings(self) -> tuple[Finding, ...]:
        return tuple(f for r in self._results.values() for f in r.findings)

    def all_artifacts(self) -> dict[str, dict[str, Any]]:
        """Every artifact published so far, keyed by plugin id.

        Used by synthesizers, which by definition need the whole picture.
        Analyzers should prefer `artifact()` with an explicit dependency.
        """
        return {pid: dict(r.artifacts) for pid, r in self._results.items()}

    def has_finding(self, check_id: str) -> bool:
        return any(f.check_id == check_id for f in self.all_findings())

    def finding(self, check_id: str) -> Finding | None:
        for f in self.all_findings():
            if f.check_id == check_id:
                return f
        return None

    # -- construction ------------------------------------------------------

    def with_result(self, result: PluginResult) -> PluginContext:
        """Return a new context including `result`. Contexts are not mutated."""
        return PluginContext(
            snapshot=self.snapshot,
            now=self.now,
            settings=self.settings,
            results={**self._results, str(result.plugin_id): result},
        )

    @classmethod
    def for_testing(
        cls,
        *,
        snapshot: SiteSnapshot,
        now: datetime | None = None,
        artifacts: Mapping[str, Mapping[str, Any]] | None = None,
        findings: Mapping[str, tuple[Finding, ...]] | None = None,
        settings: PluginSettings | None = None,
    ) -> PluginContext:
        """Build a context with dependency output stubbed directly.

        This is the point of the plugin boundary: to test `cms`, you hand it a
        fake `technologies` artifact. You never run the real technologies
        plugin, so a bug there cannot make a cms test fail.
        """
        from leadkhojo.core.utils.clock import utcnow  # local: keeps module import-light

        results: dict[str, PluginResult] = {}
        for pid, arts in (artifacts or {}).items():
            results[pid] = PluginResult(plugin_id=PluginId(pid), artifacts=dict(arts))
        for pid, fs in (findings or {}).items():
            existing = results.get(pid)
            results[pid] = PluginResult(
                plugin_id=PluginId(pid),
                findings=fs,
                artifacts=existing.artifacts if existing else {},
            )
        return cls(
            snapshot=snapshot,
            now=now or utcnow(),
            settings=settings,
            results=results,
        )


@runtime_checkable
class Plugin(Protocol):
    """Every unit of analysis implements this and nothing more."""

    meta: ClassVar[PluginMeta]

    def run(self, ctx: PluginContext) -> PluginResult: ...


class BasePlugin:
    """Optional convenience base. Implementing the Protocol directly is fine."""

    meta: ClassVar[PluginMeta]

    @property
    def id(self) -> str:
        return self.meta.id

    def run(self, ctx: PluginContext) -> PluginResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def _result(
        self,
        findings: tuple[Finding, ...] = (),
        artifacts: Mapping[str, Any] | None = None,
        opportunities: tuple[Opportunity, ...] = (),
    ) -> PluginResult:
        return PluginResult(
            plugin_id=PluginId(self.meta.id),
            findings=findings,
            artifacts=dict(artifacts or {}),
            opportunities=opportunities,
        )
