"""Technology detection tests — fingerprint matching and CMS analysis.

Two plugins: `technologies` matches declarative fingerprints against the
snapshot; `cms` depends on its output. The cms tests stub that dependency
directly, which is the point of the plugin boundary.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from leadkhojo.core.errors import RuleLoadError
from leadkhojo.core.types import FindingStatus
from leadkhojo.plugins.base import PluginContext
from leadkhojo.plugins.builtin.cms_plugin import CmsPlugin
from leadkhojo.plugins.builtin.technologies_plugin import TechnologiesPlugin
from leadkhojo.plugins.rules import load_fingerprints, load_rule_packs
from tests.conftest import make_page, make_snapshot

REPO_RULES = Path(__file__).resolve().parents[3] / "rules"


@pytest.fixture(scope="module")
def packs():  # type: ignore[no-untyped-def]
    return load_rule_packs(REPO_RULES)


def _detect(packs, now: datetime, *, html: str = "", headers: dict | None = None) -> dict:  # type: ignore[no-untyped-def]
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(pages=(make_page(html=html, headers=headers or {}),)),
        now=now,
    )
    result = TechnologiesPlugin(packs).run(ctx)
    return {t["id"]: t for t in result.artifacts["technologies"]}


# ---------------------------------------------------------------- rule loading


def test_the_shipped_rule_packs_load_and_validate() -> None:
    fingerprints = load_fingerprints(REPO_RULES)
    assert len(fingerprints) >= 50

    ids = [str(f.id) for f in fingerprints]
    assert len(ids) == len(set(ids)), "fingerprint ids must be unique"
    assert ids == sorted(ids), "fingerprints must load in deterministic order"


def test_every_fingerprint_has_at_least_one_signal() -> None:
    for fingerprint in load_fingerprints(REPO_RULES):
        assert fingerprint.signals, f"{fingerprint.id} has no signals"


def test_a_malformed_rule_pack_fails_at_startup(tmp_path: Path) -> None:
    """Discovering a bad rule mid-scan, on someone's fortieth site, is
    strictly worse than failing the boot."""
    tech = tmp_path / "technology"
    tech.mkdir()
    (tech / "broken.yaml").write_text(
        "- id: broken\n  category: cms\n  signals:\n"
        "    - {type: html, pattern: '([unclosed'}\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleLoadError, match="invalid regex"):
        load_fingerprints(tmp_path)


def test_an_unknown_signal_type_is_rejected(tmp_path: Path) -> None:
    tech = tmp_path / "technology"
    tech.mkdir()
    (tech / "x.yaml").write_text(
        "- id: x\n  category: cms\n  signals:\n    - {type: telepathy, pattern: 'a'}\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleLoadError, match="unknown signal type"):
        load_fingerprints(tmp_path)


# ---------------------------------------------------------------- matching


def test_wordpress_is_detected_from_a_generator_tag_with_its_version(packs, now) -> None:  # type: ignore[no-untyped-def]
    html = '<html><head><meta name="generator" content="WordPress 5.4.2"></head></html>'
    detected = _detect(packs, now, html=html)

    assert "wordpress" in detected
    assert detected["wordpress"]["version"] == "5.4.2"
    assert detected["wordpress"]["confidence"] == "certain"
    assert detected["wordpress"]["evidence"]


def test_wordpress_is_detected_from_asset_paths_without_a_version(packs, now) -> None:  # type: ignore[no-untyped-def]
    html = '<link href="/wp-content/themes/x/style.css">'
    detected = _detect(packs, now, html=html)

    assert "wordpress" in detected
    assert detected["wordpress"]["version"] is None
    # No version means we cannot judge currency — and must not pretend to.
    assert detected["wordpress"]["is_outdated"] is None


def test_a_known_old_version_is_flagged_outdated(packs, now) -> None:  # type: ignore[no-untyped-def]
    html = '<meta name="generator" content="WordPress 5.4.2">'
    detected = _detect(packs, now, html=html)

    assert detected["wordpress"]["is_outdated"] is True
    assert detected["wordpress"]["versions_behind"] >= 1


def test_a_current_version_is_not_flagged(packs, now) -> None:  # type: ignore[no-untyped-def]
    latest = packs.latest_versions["wordpress"]
    html = f'<meta name="generator" content="WordPress {latest}">'
    detected = _detect(packs, now, html=html)

    assert detected["wordpress"]["is_outdated"] is False


def test_server_headers_are_matched_with_versions(packs, now) -> None:  # type: ignore[no-untyped-def]
    detected = _detect(packs, now, headers={"server": "nginx/1.18.0"})

    assert "nginx" in detected
    assert detected["nginx"]["version"] == "1.18.0"


def test_cdn_is_detected_from_a_marker_header(packs, now) -> None:  # type: ignore[no-untyped-def]
    detected = _detect(packs, now, headers={"cf-ray": "abc123-LHR"})
    assert "cloudflare" in detected


def test_analytics_detection_sets_the_has_analytics_flag(packs, now) -> None:  # type: ignore[no-untyped-def]
    ctx = PluginContext.for_testing(
        snapshot=make_snapshot(
            pages=(make_page(html='<script src="https://www.googletagmanager.com/gtm.js"></script>'),)
        ),
        now=now,
    )
    result = TechnologiesPlugin(packs).run(ctx)
    assert result.artifacts["has_analytics"] is True


def test_a_clean_page_detects_nothing_rather_than_guessing(packs, now) -> None:  # type: ignore[no-untyped-def]
    detected = _detect(packs, now, html="<html><body><h1>Hello</h1></body></html>")
    assert detected == {}


def test_detection_output_is_deterministic(packs, now) -> None:  # type: ignore[no-untyped-def]
    html = '<meta name="generator" content="WordPress 5.4.2"><link href="/wp-content/x.css">'
    runs = [list(_detect(packs, now, html=html)) for _ in range(10)]
    assert all(run == runs[0] for run in runs)


def test_an_empty_snapshot_is_handled(packs, now) -> None:  # type: ignore[no-untyped-def]
    ctx = PluginContext.for_testing(snapshot=make_snapshot(pages=()), now=now)
    result = TechnologiesPlugin(packs).run(ctx)
    assert result.artifacts["technologies"] == []


# ---------------------------------------------------------------- CMS plugin
# Dependency stubbed directly — the real technologies plugin never runs.


def _cms_ctx(now: datetime, tech: dict | None) -> PluginContext:
    return PluginContext.for_testing(
        snapshot=make_snapshot(),
        now=now,
        artifacts={"technologies": {"technologies": [tech] if tech else []}},
    )


def test_cms_reads_a_stubbed_dependency(now: datetime) -> None:
    result = CmsPlugin().run(
        _cms_ctx(
            now,
            {
                "id": "wordpress",
                "name": "WordPress",
                "category": "cms",
                "version": "5.4.2",
                "confidence": "certain",
                "is_outdated": True,
                "versions_behind": 1,
                "evidence": {"meta_generator": "WordPress 5.4.2"},
            },
        )
    )

    finding = next(f for f in result.findings if f.check_id == "CMS-02")
    assert finding.status is FindingStatus.FAIL
    assert finding.evidence["detected_version"] == "5.4.2"
    assert result.artifacts["cms"]["name"] == "WordPress"


def test_an_unknown_version_says_nothing_rather_than_something_vague(now: datetime) -> None:
    """The specificity gate. 'Your CMS might be outdated' wastes the user's
    attention and teaches them to distrust every other row."""
    result = CmsPlugin().run(
        _cms_ctx(
            now,
            {
                "id": "wordpress",
                "name": "WordPress",
                "category": "cms",
                "version": None,
                "confidence": "certain",
                "is_outdated": None,
                "versions_behind": None,
                "evidence": {},
            },
        )
    )
    finding = next(f for f in result.findings if f.check_id == "CMS-02")
    assert finding.status is FindingStatus.NOT_APPLICABLE


def test_a_current_cms_passes(now: datetime) -> None:
    result = CmsPlugin().run(
        _cms_ctx(
            now,
            {
                "id": "wordpress",
                "name": "WordPress",
                "category": "cms",
                "version": "6.7",
                "confidence": "certain",
                "is_outdated": False,
                "versions_behind": 0,
                "evidence": {},
            },
        )
    )
    assert next(f for f in result.findings if f.check_id == "CMS-02").status is FindingStatus.PASS


def test_no_cms_detected_is_reported_without_alarm(now: datetime) -> None:
    result = CmsPlugin().run(_cms_ctx(now, None))
    assert result.artifacts["cms"] is None
    assert next(f for f in result.findings if f.check_id == "CMS-01").status is FindingStatus.INFO


def test_cms_declares_its_dependency_rather_than_importing_it() -> None:
    assert CmsPlugin.meta.depends_on == ("technologies",)
