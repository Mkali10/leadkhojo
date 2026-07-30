"""robots.txt fetching and enforcement.

There is no override. A disallowed path is not fetched, and no flag exists to
change that. If you find yourself wanting one, re-read docs/11-SECURITY-RULES.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from leadkhojo.crawler.snapshot import RobotsInfo

_LINE_RE = re.compile(r"^\s*([A-Za-z-]+)\s*:\s*(.*?)\s*(?:#.*)?$")


@dataclass(frozen=True, slots=True)
class RobotsRules:
    """Parsed rules applicable to *our* user agent."""

    disallowed: tuple[str, ...] = ()
    allowed: tuple[str, ...] = ()
    sitemaps: tuple[str, ...] = ()
    exists: bool = False
    crawl_delay: float | None = None

    def is_allowed(self, url: str) -> bool:
        """Longest-match wins, as per the robots.txt convention."""
        path = urlparse(url).path or "/"

        best_allow = max((len(p) for p in self.allowed if _matches(path, p)), default=-1)
        best_deny = max((len(p) for p in self.disallowed if _matches(path, p)), default=-1)

        if best_deny < 0:
            return True
        return best_allow >= best_deny

    @property
    def blocks_everything(self) -> bool:
        return "/" in self.disallowed and not self.allowed

    def to_info(self) -> RobotsInfo:
        return RobotsInfo(
            exists=self.exists,
            disallowed_paths=self.disallowed,
            sitemaps=self.sitemaps,
            blocked_us=self.blocks_everything,
        )


def _matches(path: str, rule: str) -> bool:
    if not rule:
        return False
    if rule.endswith("$"):
        return path == rule[:-1]
    if "*" in rule:
        pattern = re.escape(rule).replace(r"\*", ".*")
        return re.match(pattern, path) is not None
    return path.startswith(rule)


def parse_robots(body: str, user_agent: str) -> RobotsRules:
    """Parse robots.txt, honouring the most specific matching agent group.

    A group naming our agent explicitly wins over the wildcard group.
    """
    groups: dict[str, dict[str, list[str]]] = {}
    sitemaps: list[str] = []
    current_agents: list[str] = []
    ua_lower = user_agent.lower().split("/")[0]

    for raw_line in body.splitlines():
        match = _LINE_RE.match(raw_line)
        if not match:
            continue
        field, value = match.group(1).lower(), match.group(2)

        if field == "sitemap":
            if value:
                sitemaps.append(value)
            continue

        if field == "user-agent":
            agent = value.lower()
            # A blank line ends a group; a new agent after rules starts one.
            current_agents = [agent]
            groups.setdefault(agent, {"disallow": [], "allow": [], "crawl-delay": []})
            continue

        if field in ("disallow", "allow", "crawl-delay") and current_agents:
            for agent in current_agents:
                groups.setdefault(agent, {"disallow": [], "allow": [], "crawl-delay": []})
                groups[agent][field].append(value)

    chosen: dict[str, list[str]] | None = None
    for agent, rules in groups.items():
        if ua_lower in agent:
            chosen = rules
            break
    if chosen is None:
        chosen = groups.get("*")

    if chosen is None:
        return RobotsRules(exists=bool(body.strip()), sitemaps=tuple(sitemaps))

    delay: float | None = None
    for value in chosen.get("crawl-delay", []):
        try:
            delay = float(value)
            break
        except ValueError:
            continue

    return RobotsRules(
        disallowed=tuple(p for p in chosen.get("disallow", []) if p),
        allowed=tuple(p for p in chosen.get("allow", []) if p),
        sitemaps=tuple(sitemaps),
        exists=True,
        crawl_delay=delay,
    )


EMPTY_ROBOTS = RobotsRules()

__all__ = ["EMPTY_ROBOTS", "RobotsRules", "parse_robots"]
