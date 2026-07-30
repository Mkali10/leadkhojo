"""Time handling.

Every timestamp in the system is UTC and timezone-aware.

The clock is *injected* into plugins via PluginContext.now. No plugin calls
utcnow() directly — otherwise a test written today breaks in thirty days when
a certificate fixture's "days remaining" silently changes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    """Current time, UTC, timezone-aware. Call sites outside plugins only."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Coerce a datetime to timezone-aware UTC.

    Certificate parsing and some DNS libraries hand back naive datetimes that
    are UTC in fact but not in type. Comparing one of those to an aware
    datetime raises TypeError, so normalize at every boundary.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso(value: datetime) -> str:
    """ISO 8601 with a Z suffix, for evidence and API output."""
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def days_between(earlier: datetime, later: datetime) -> int:
    """Whole days from `earlier` to `later`. Negative if `later` is in the past."""
    delta: timedelta = ensure_utc(later) - ensure_utc(earlier)
    return delta.days
