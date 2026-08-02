"""The core engine.

Knows nothing about SSL, DNS, or WordPress. It resolves a dependency graph,
runs plugins in a deterministic order, isolates failures, and records timing.

Guarantees:
  * deterministic order   — topological sort, alphabetical tie-break
  * failure isolation     — a raising plugin never stops the others
  * dependency safety     — a plugin whose dependency failed is skipped
  * no partial reads      — a plugin only sees results already produced
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from leadkhojo.core.findings import Finding, sort_findings
from leadkhojo.core.types import PluginId
from leadkhojo.plugins.base import Plugin, PluginContext, PluginResult, PluginSettings

if TYPE_CHECKING:
    from leadkhojo.crawler.snapshot import SiteSnapshot
    from leadkhojo.opportunities.schemas import Opportunity

logger = logging.getLogger(__name__)


class PluginGraphError(Exception):
    """The plugin set is not runnable. Raised at startup, never mid-scan."""


@dataclass(frozen=True, slots=True)
class PluginRun:
    plugin_id: str
    ok: bool
    duration_ms: int
    finding_count: int = 0
    skipped_reason: str | None = None
    error: str | None = None

    @property
    def over_budget(self) -> bool:
        return self.ok and self.duration_ms > 0


@dataclass(frozen=True, slots=True)
class EngineReport:
    """The full output of one analysis pass."""

    findings: tuple[Finding, ...] = ()
    opportunities: tuple[Opportunity, ...] = ()
    artifacts: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    runs: tuple[PluginRun, ...] = ()
    total_ms: int = 0

    @property
    def failed_plugins(self) -> tuple[str, ...]:
        return tuple(r.plugin_id for r in self.runs if not r.ok)

    @property
    def problems(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.is_problem)

    def artifact(self, plugin_id: str, key: str, default: object = None) -> object:
        return self.artifacts.get(plugin_id, {}).get(key, default)


def resolve_order(plugins: Sequence[Plugin]) -> tuple[Plugin, ...]:
    """Topologically sort plugins by declared dependencies.

    Ties are broken alphabetically by id so the order is identical on every
    run and on every machine — a prerequisite for deterministic output.
    """
    by_id: dict[str, Plugin] = {}
    for plugin in plugins:
        pid = plugin.meta.id
        if pid in by_id:
            raise PluginGraphError(f"Duplicate plugin id: {pid!r}")
        by_id[pid] = plugin

    for plugin in plugins:
        for dep in plugin.meta.depends_on:
            if dep not in by_id:
                raise PluginGraphError(
                    f"Plugin {plugin.meta.id!r} depends on {dep!r}, which is not registered"
                )

    ordered: list[Plugin] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def visit(pid: str, trail: tuple[str, ...]) -> None:
        if pid in placed:
            return
        if pid in visiting:
            cycle = " -> ".join([*trail, pid])
            raise PluginGraphError(f"Dependency cycle: {cycle}")
        visiting.add(pid)
        for dep in sorted(by_id[pid].meta.depends_on):
            visit(dep, (*trail, pid))
        visiting.discard(pid)
        placed.add(pid)
        ordered.append(by_id[pid])

    for pid in sorted(by_id):
        visit(pid, ())

    return tuple(ordered)


class PluginEngine:
    """Runs a plugin set against a snapshot."""

    def __init__(
        self,
        plugins: Iterable[Plugin],
        *,
        settings: PluginSettings | None = None,
        disabled: Iterable[str] = (),
    ) -> None:
        disabled_set = set(disabled)
        selected = [p for p in plugins if p.meta.id not in disabled_set]
        # Drop plugins whose dependencies were disabled, rather than exploding.
        available = {p.meta.id for p in selected}
        self._plugins = resolve_order([p for p in selected if set(p.meta.depends_on) <= available])
        self._settings = settings or PluginSettings()
        self._disabled = disabled_set

    @property
    def plugin_ids(self) -> tuple[str, ...]:
        return tuple(p.meta.id for p in self._plugins)

    @property
    def plugins(self) -> tuple[Plugin, ...]:
        """The enabled plugin set, in execution order.

        Exposed so the API can describe itself without re-loading every rule
        pack on each request.
        """
        return self._plugins

    def run(self, snapshot: SiteSnapshot, *, now: datetime) -> EngineReport:
        ctx = PluginContext(snapshot=snapshot, now=now, settings=self._settings)

        runs: list[PluginRun] = []
        all_findings: list[Finding] = []
        all_opportunities: list[Opportunity] = []
        artifacts: dict[str, Mapping[str, object]] = {}
        failed: set[str] = set()

        engine_start = time.perf_counter()

        for plugin in self._plugins:
            pid = plugin.meta.id

            blocked = sorted(set(plugin.meta.depends_on) & failed)
            if blocked:
                reason = f"dependency failed: {', '.join(blocked)}"
                logger.warning("plugin.skipped", extra={"plugin": pid, "reason": reason})
                runs.append(
                    PluginRun(plugin_id=pid, ok=False, duration_ms=0, skipped_reason=reason)
                )
                failed.add(pid)
                continue

            started = time.perf_counter()
            try:
                result = plugin.run(ctx)
            except Exception as exc:
                duration = int((time.perf_counter() - started) * 1000)
                logger.exception("plugin.failed", extra={"plugin": pid})
                runs.append(
                    PluginRun(
                        plugin_id=pid,
                        ok=False,
                        duration_ms=duration,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                failed.add(pid)
                continue

            duration = int((time.perf_counter() - started) * 1000)

            undeclared = set(result.artifacts) - set(plugin.meta.provides)
            if undeclared:
                # Not fatal, but it means a dependent cannot rely on the key.
                logger.warning(
                    "plugin.undeclared_artifacts",
                    extra={"plugin": pid, "keys": sorted(undeclared)},
                )

            if duration > plugin.meta.budget_ms:
                logger.warning(
                    "plugin.over_budget",
                    extra={"plugin": pid, "ms": duration, "budget_ms": plugin.meta.budget_ms},
                )

            ctx = ctx.with_result(result)
            all_findings.extend(result.findings)
            all_opportunities.extend(result.opportunities)
            if result.artifacts:
                artifacts[pid] = dict(result.artifacts)

            runs.append(
                PluginRun(
                    plugin_id=pid,
                    ok=True,
                    duration_ms=duration,
                    finding_count=len(result.findings),
                )
            )

        return EngineReport(
            findings=sort_findings(tuple(all_findings)),
            opportunities=tuple(all_opportunities),
            artifacts=artifacts,
            runs=tuple(runs),
            total_ms=int((time.perf_counter() - engine_start) * 1000),
        )

    def run_one(self, plugin_id: str, snapshot: SiteSnapshot, *, now: datetime) -> PluginResult:
        """Run a single plugin plus its dependency chain.

        Used by tests and by `reanalyze --plugin`. Keeps the "independently
        testable" promise honest at the engine level too.
        """
        wanted = self._chain_for(plugin_id)
        sub = PluginEngine(wanted, settings=self._settings)
        report = sub.run(snapshot, now=now)
        target = [r for r in report.runs if r.plugin_id == plugin_id]
        if not target or not target[0].ok:
            return PluginResult.empty(plugin_id)
        return PluginResult(
            plugin_id=PluginId(plugin_id),
            findings=tuple(f for f in report.findings if f.plugin_id == plugin_id),
            artifacts=dict(report.artifacts.get(plugin_id, {})),
            opportunities=report.opportunities,
        )

    def _chain_for(self, plugin_id: str) -> list[Plugin]:
        by_id = {p.meta.id: p for p in self._plugins}
        if plugin_id not in by_id:
            raise PluginGraphError(f"Unknown plugin: {plugin_id!r}")
        needed: set[str] = set()

        def walk(pid: str) -> None:
            if pid in needed:
                return
            needed.add(pid)
            for dep in by_id[pid].meta.depends_on:
                walk(dep)

        walk(plugin_id)
        return [by_id[pid] for pid in needed]
