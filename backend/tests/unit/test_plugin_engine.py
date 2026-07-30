"""Plugin engine unit tests.

The engine's four guarantees, each tested with stub plugins so the tests
depend on no real analyser:

  * deterministic order      — same set, same order, every run
  * failure isolation        — a raising plugin never stops the others
  * dependency safety        — a plugin whose dependency failed is skipped
  * no partial reads         — a plugin only sees results already produced
"""

from __future__ import annotations

from datetime import datetime

import pytest

from leadkhojo.core.types import PluginId
from leadkhojo.plugins.base import (
    BasePlugin,
    PluginContext,
    PluginKind,
    PluginMeta,
    PluginResult,
)
from leadkhojo.plugins.engine import PluginEngine, PluginGraphError, resolve_order
from tests.conftest import make_snapshot


class _Stub(BasePlugin):
    def __init__(self, plugin_id: str, depends_on: tuple[str, ...] = ()) -> None:
        self.meta = PluginMeta(  # type: ignore[misc]
            id=plugin_id,
            name=plugin_id,
            version="1.0.0",
            kind=PluginKind.ANALYZER,
            depends_on=depends_on,
            provides=("value",),
        )

    def run(self, ctx: PluginContext) -> PluginResult:
        return PluginResult(plugin_id=PluginId(self.meta.id), artifacts={"value": self.meta.id})


class _Exploding(_Stub):
    def run(self, ctx: PluginContext) -> PluginResult:
        raise RuntimeError("boom")


class _Slow(_Stub):
    def run(self, ctx: PluginContext) -> PluginResult:
        import time

        time.sleep(0.01)
        return super().run(ctx)


# ---------------------------------------------------------------- ordering


def test_dependencies_run_before_dependents() -> None:
    order = resolve_order([_Stub("cms", ("technologies",)), _Stub("technologies")])
    assert [p.meta.id for p in order] == ["technologies", "cms"]


def test_order_is_deterministic_across_input_orderings() -> None:
    """Same plugin set -> same order, every run, every machine.

    Output determinism is impossible without this.
    """
    plugins = [_Stub("zebra"), _Stub("alpha"), _Stub("mango")]
    first = [p.meta.id for p in resolve_order(plugins)]
    second = [p.meta.id for p in resolve_order(list(reversed(plugins)))]
    assert first == second == ["alpha", "mango", "zebra"]


def test_a_deep_dependency_chain_resolves() -> None:
    order = resolve_order([_Stub("d", ("c",)), _Stub("c", ("b",)), _Stub("b", ("a",)), _Stub("a")])
    assert [p.meta.id for p in order] == ["a", "b", "c", "d"]


def test_a_dependency_cycle_fails_loudly() -> None:
    with pytest.raises(PluginGraphError, match="cycle"):
        resolve_order([_Stub("a", ("b",)), _Stub("b", ("a",))])


def test_a_missing_dependency_fails_at_startup_not_mid_scan() -> None:
    with pytest.raises(PluginGraphError, match="not registered"):
        resolve_order([_Stub("cms", ("technologies",))])


def test_duplicate_plugin_ids_are_rejected() -> None:
    with pytest.raises(PluginGraphError, match="Duplicate"):
        resolve_order([_Stub("ssl"), _Stub("ssl")])


def test_a_plugin_cannot_depend_on_itself() -> None:
    with pytest.raises(ValueError, match="itself"):
        PluginMeta(
            id="ssl", name="SSL", version="1.0.0", kind=PluginKind.ANALYZER, depends_on=("ssl",)
        )


# ---------------------------------------------------------------- isolation


def test_a_failing_plugin_does_not_stop_the_others(now: datetime) -> None:
    engine = PluginEngine([_Exploding("broken"), _Stub("healthy")])
    report = engine.run(make_snapshot(), now=now)

    assert "broken" in report.failed_plugins
    assert report.artifacts["healthy"]["value"] == "healthy"
    assert next(r for r in report.runs if r.plugin_id == "healthy").ok


def test_the_error_is_recorded_not_swallowed(now: datetime) -> None:
    engine = PluginEngine([_Exploding("broken")])
    report = engine.run(make_snapshot(), now=now)

    run = next(r for r in report.runs if r.plugin_id == "broken")
    assert not run.ok
    assert run.error is not None
    assert "RuntimeError" in run.error


def test_a_dependent_of_a_failed_plugin_is_skipped_not_run_blind(now: datetime) -> None:
    """Running a plugin with missing input produces confidently wrong output,
    which is worse than producing nothing."""
    engine = PluginEngine([_Exploding("technologies"), _Stub("cms", ("technologies",))])
    report = engine.run(make_snapshot(), now=now)

    cms_run = next(r for r in report.runs if r.plugin_id == "cms")
    assert not cms_run.ok
    assert cms_run.skipped_reason is not None
    assert "technologies" in cms_run.skipped_reason
    assert cms_run.error is None  # skipped, not crashed


# ---------------------------------------------------------------- context


def test_a_plugin_only_sees_results_already_produced(now: datetime) -> None:
    seen: dict[str, list[str]] = {}

    class _Watcher(_Stub):
        def run(self, ctx: PluginContext) -> PluginResult:
            seen[self.meta.id] = sorted(ctx.all_artifacts())
            return super().run(ctx)

    engine = PluginEngine([_Watcher("second", ("first",)), _Watcher("first")])
    engine.run(make_snapshot(), now=now)

    assert seen["first"] == []
    assert seen["second"] == ["first"]


def test_context_is_never_mutated(now: datetime) -> None:
    ctx = PluginContext(snapshot=make_snapshot(), now=now)
    extended = ctx.with_result(PluginResult(plugin_id=PluginId("a"), artifacts={"k": 1}))

    assert ctx.artifact("a", "k") is None
    assert extended.artifact("a", "k") == 1


def test_for_testing_stubs_dependency_output_directly(now: datetime) -> None:
    """The point of the plugin boundary: a dependent is testable without
    ever running the plugin it depends on."""
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(),
        now=now,
        artifacts={"technologies": {"technologies": [{"id": "wordpress"}]}},
    )
    assert ctx.artifact("technologies", "technologies")[0]["id"] == "wordpress"
    assert ctx.artifact("technologies", "missing", "fallback") == "fallback"
    assert ctx.artifact("never_ran", "anything") is None


# ---------------------------------------------------------------- selection


def test_disabled_plugins_are_excluded(now: datetime) -> None:
    engine = PluginEngine([_Stub("ssl"), _Stub("dns")], disabled=["dns"])
    assert engine.plugin_ids == ("ssl",)


def test_disabling_a_dependency_drops_its_dependents_rather_than_exploding() -> None:
    engine = PluginEngine(
        [_Stub("technologies"), _Stub("cms", ("technologies",))], disabled=["technologies"]
    )
    assert engine.plugin_ids == ()


def test_timing_is_recorded_for_every_plugin(now: datetime) -> None:
    engine = PluginEngine([_Slow("slow")])
    report = engine.run(make_snapshot(), now=now)

    run = next(r for r in report.runs if r.plugin_id == "slow")
    assert run.duration_ms >= 0
    assert report.total_ms >= 0
