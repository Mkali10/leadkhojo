"""HTTP surface.

The React UI consumes this and nothing else. No client — browser, script or
future mobile app — reaches into `leadkhojo.pipeline` or `leadkhojo.plugins`
directly; everything goes through the contract in `schemas.py`.
"""

from __future__ import annotations

__all__: list[str] = []
