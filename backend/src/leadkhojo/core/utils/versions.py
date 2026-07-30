"""Version comparison that survives real-world version strings.

Real sites serve "5.4.2", "5.4.2-beta1", "v2.0", "1.10.0" and worse. The naive
tuple(map(int, s.split("."))) approach fails on all but the first, and gets
"1.10" < "1.9" wrong — which would flag a current site as outdated and put a
false claim in front of a prospect.
"""

from __future__ import annotations

import re
from functools import total_ordering

_VERSION_RE = re.compile(r"^[vV]?(\d+(?:\.\d+)*)(?:[-+._]?(.*))?$")


@total_ordering
class Version:
    """A comparable, lenient version.

    Pre-release suffixes sort *below* the same numeric release, so
    5.4.2-beta < 5.4.2, which matches every packaging convention that matters.
    """

    __slots__ = ("parts", "prerelease", "raw")

    def __init__(self, raw: str) -> None:
        self.raw = raw.strip()
        match = _VERSION_RE.match(self.raw)
        if not match:
            self.parts: tuple[int, ...] = ()
            self.prerelease: str = ""
            return
        self.parts = tuple(int(p) for p in match.group(1).split("."))
        self.prerelease = (match.group(2) or "").lower()

    @property
    def is_valid(self) -> bool:
        return bool(self.parts)

    @property
    def major(self) -> int:
        return self.parts[0] if self.parts else 0

    def _padded(self, length: int) -> tuple[int, ...]:
        return self.parts + (0,) * (length - len(self.parts))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        length = max(len(self.parts), len(other.parts))
        return self._padded(length) == other._padded(length) and self.prerelease == other.prerelease

    def __lt__(self, other: Version) -> bool:
        length = max(len(self.parts), len(other.parts))
        mine, theirs = self._padded(length), other._padded(length)
        if mine != theirs:
            return mine < theirs
        # Same numbers: a prerelease is older than the final release.
        if self.prerelease and not other.prerelease:
            return True
        if not self.prerelease and other.prerelease:
            return False
        return self.prerelease < other.prerelease

    def __hash__(self) -> int:
        return hash((self.parts, self.prerelease))

    def __repr__(self) -> str:
        return f"Version({self.raw!r})"


def parse(raw: str | None) -> Version | None:
    if not raw:
        return None
    version = Version(raw)
    return version if version.is_valid else None


def is_outdated(current: str | None, latest: str | None) -> bool | None:
    """Is `current` behind `latest`?

    Returns None when we cannot tell. None is a real answer and the caller must
    handle it: the opportunity engine's specificity gate refuses to produce
    "your CMS might be old" from an unknown version.
    """
    c, latest_v = parse(current), parse(latest)
    if c is None or latest_v is None:
        return None
    return c < latest_v


def major_versions_behind(current: str | None, latest: str | None) -> int | None:
    c, latest_v = parse(current), parse(latest)
    if c is None or latest_v is None:
        return None
    return max(0, latest_v.major - c.major)
