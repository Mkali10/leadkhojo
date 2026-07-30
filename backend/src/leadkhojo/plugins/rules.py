"""Rule pack loading.

Rules are data, not code. Adding a technology fingerprint or an opportunity
rule is a YAML change plus a test — no Python edit, no migration.

Packs are loaded and validated at STARTUP. A malformed file must fail the boot
loudly; discovering it mid-scan, on someone's fortieth site, is strictly worse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from leadkhojo.core.errors import RuleLoadError
from leadkhojo.core.types import Confidence, TechCategory, TechnologyId

SignalType = Literal["meta_generator", "html", "header", "cookie", "script_src", "url"]

_VALID_SIGNALS: frozenset[str] = frozenset(
    ("meta_generator", "html", "header", "cookie", "script_src", "url")
)


@dataclass(frozen=True, slots=True)
class Signal:
    type: SignalType
    pattern: str
    confidence: Confidence = Confidence.LIKELY
    name: str | None = None  # header/cookie name
    version_group: int | None = None
    _compiled: re.Pattern[str] | None = field(default=None, compare=False, repr=False)

    @property
    def regex(self) -> re.Pattern[str]:
        if self._compiled is not None:
            return self._compiled
        return re.compile(self.pattern, re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Fingerprint:
    id: TechnologyId
    name: str
    category: TechCategory
    signals: tuple[Signal, ...]
    website: str | None = None
    latest_version: str | None = None

    def __post_init__(self) -> None:
        if not self.signals:
            raise RuleLoadError(f"Fingerprint {self.id!r} has no signals")


@dataclass(frozen=True, slots=True)
class RulePacks:
    fingerprints: tuple[Fingerprint, ...]
    latest_versions: dict[str, str]

    def by_category(self, category: TechCategory) -> tuple[Fingerprint, ...]:
        return tuple(f for f in self.fingerprints if f.category is category)


def _compile_signal(raw: dict[str, Any], tech_id: str) -> Signal:
    signal_type = raw.get("type")
    if signal_type not in _VALID_SIGNALS:
        raise RuleLoadError(
            f"{tech_id}: unknown signal type {signal_type!r}. Valid types: {sorted(_VALID_SIGNALS)}"
        )
    pattern = raw.get("pattern")
    if not pattern:
        raise RuleLoadError(f"{tech_id}: signal is missing 'pattern'")

    try:
        compiled = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise RuleLoadError(f"{tech_id}: invalid regex {pattern!r}: {exc}") from exc

    if signal_type in ("header", "cookie") and not raw.get("name"):
        raise RuleLoadError(f"{tech_id}: {signal_type} signal requires a 'name'")

    confidence_raw = raw.get("confidence", "likely")
    try:
        confidence = Confidence(confidence_raw)
    except ValueError as exc:
        raise RuleLoadError(f"{tech_id}: unknown confidence {confidence_raw!r}") from exc

    return Signal(
        type=signal_type,  # type: ignore[arg-type]
        pattern=pattern,
        confidence=confidence,
        name=raw.get("name"),
        version_group=raw.get("version_group"),
        _compiled=compiled,
    )


def load_fingerprints(rules_dir: Path) -> tuple[Fingerprint, ...]:
    tech_dir = rules_dir / "technology"
    if not tech_dir.is_dir():
        raise RuleLoadError(f"Technology rules directory not found: {tech_dir}")

    fingerprints: list[Fingerprint] = []
    seen: set[str] = set()

    for path in sorted(tech_dir.glob("*.yaml")):
        if path.name == "known_versions.yaml":
            continue
        try:
            documents = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        except yaml.YAMLError as exc:
            raise RuleLoadError(f"{path.name}: invalid YAML: {exc}") from exc

        if not isinstance(documents, list):
            raise RuleLoadError(f"{path.name}: expected a list of fingerprints")

        for entry in documents:
            tech_id = entry.get("id")
            if not tech_id:
                raise RuleLoadError(f"{path.name}: a fingerprint is missing 'id'")
            if tech_id in seen:
                raise RuleLoadError(f"Duplicate technology id: {tech_id!r}")
            seen.add(tech_id)

            try:
                category = TechCategory(entry["category"])
            except (KeyError, ValueError) as exc:
                raise RuleLoadError(
                    f"{tech_id}: missing or unknown category {entry.get('category')!r}"
                ) from exc

            signals = tuple(_compile_signal(s, tech_id) for s in (entry.get("signals") or []))
            fingerprints.append(
                Fingerprint(
                    id=TechnologyId(tech_id),
                    name=entry.get("name", tech_id),
                    category=category,
                    signals=signals,
                    website=entry.get("website"),
                    latest_version=entry.get("latest_version"),
                )
            )

    if not fingerprints:
        raise RuleLoadError(f"No fingerprints loaded from {tech_dir}")

    # Deterministic order so detection output is stable across runs.
    return tuple(sorted(fingerprints, key=lambda f: f.id))


def load_latest_versions(rules_dir: Path) -> dict[str, str]:
    path = rules_dir / "technology" / "known_versions.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise RuleLoadError(f"known_versions.yaml: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RuleLoadError("known_versions.yaml: expected a mapping of id -> version")
    return {str(k): str(v) for k, v in data.items()}


@lru_cache(maxsize=4)
def load_rule_packs(rules_dir: Path) -> RulePacks:
    """Load and validate everything. Cached — packs are immutable at runtime."""
    fingerprints = load_fingerprints(rules_dir)
    latest = load_latest_versions(rules_dir)
    merged = tuple(
        Fingerprint(
            id=f.id,
            name=f.name,
            category=f.category,
            signals=f.signals,
            website=f.website,
            latest_version=f.latest_version or latest.get(str(f.id)),
        )
        for f in fingerprints
    )
    return RulePacks(fingerprints=merged, latest_versions=latest)
