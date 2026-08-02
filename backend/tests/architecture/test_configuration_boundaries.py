"""Architecture guards for configuration.

config.py claims to be the only place in the codebase that reads the
environment, and the .env.example claims to list everything an operator can
change. Both claims decay silently the first time someone reaches for
os.getenv in a hurry. These tests make them fail loudly instead.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "leadkhojo"
CONFIG = SRC / "core" / "config.py"


def _python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in str(p))


def test_only_config_reads_the_environment() -> None:
    """One place to look when a value is wrong, and one place to document.

    A stray os.getenv is a setting that never appears in .env.example, never
    gets validated at startup, and is discovered by whoever is debugging at
    3am.
    """
    violations: list[str] = []

    for path in _python_files():
        if path == CONFIG:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            # os.getenv(...) / os.environ.get(...) / environ[...]
            if isinstance(node, ast.Attribute) and node.attr in ("getenv", "environ"):
                violations.append(f"{path.relative_to(SRC)}:{node.lineno} os.{node.attr}")
            elif isinstance(node, ast.Name) and node.id in ("getenv", "environ"):
                violations.append(f"{path.relative_to(SRC)}:{node.lineno} {node.id}")

    assert not violations, "Environment read outside config.py:\n  " + "\n  ".join(violations)


def test_no_connection_string_is_hardcoded() -> None:
    """A credential in source is a credential in the git history for ever."""
    pattern = re.compile(r"(postgres|postgresql|mysql|redis|amqp)(\+\w+)?://")
    violations: list[str] = []

    for path in _python_files():
        if path == CONFIG:  # the documented default lives here, with no real secret
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                violations.append(f"{path.relative_to(SRC)}:{number}")

    assert not violations, "Hardcoded connection string:\n  " + "\n  ".join(violations)


def test_the_bind_address_is_not_hardcoded() -> None:
    """Someone hardcoding 0.0.0.0 for convenience would silently expose an
    instance that has no authentication."""
    violations: list[str] = []

    for path in _python_files():
        if path == CONFIG:  # binds_publicly has to name the addresses it detects
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # An exact literal only. The crawler's SSRF blocklist legitimately
            # contains "0.0.0.0/8", which is the opposite of a bind address.
            if isinstance(node, ast.Constant) and node.value in ("0.0.0.0", "::"):
                violations.append(f"{path.relative_to(SRC)}:{node.lineno}")

    assert not violations, "Hardcoded bind address:\n  " + "\n  ".join(violations)
