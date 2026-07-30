"""Exception hierarchy.

Rule: never `raise Exception`, never bare `except:`. Every error carries a
machine-readable code and an HTTP status so the API layer needs no mapping
table.

Crawl failures are deliberately NOT exceptions — they are data recorded on the
snapshot (see core.types.CrawlFailure). CrawlError exists only for the cases
where we refuse to proceed at all, such as a blocked address.
"""

from __future__ import annotations

from typing import Any


class LeadKhojoError(Exception):
    code: str = "internal_error"
    status_code: int = 500

    def __init__(self, message: str, *, meta: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.meta = meta or {}

    def to_problem(self, correlation_id: str | None = None) -> dict[str, Any]:
        """RFC 9457 Problem Details."""
        problem: dict[str, Any] = {
            "type": f"https://docs.leadkhojo.com/errors/{self.code.replace('_', '-')}",
            "title": self.__class__.__name__,
            "status": self.status_code,
            "detail": self.message,
            "code": self.code,
        }
        if correlation_id:
            problem["correlation_id"] = correlation_id
        if self.meta:
            problem["meta"] = self.meta
        return problem


class NotFoundError(LeadKhojoError):
    code, status_code = "not_found", 404


class ValidationError(LeadKhojoError):
    code, status_code = "validation_failed", 422


class InvalidCsvError(LeadKhojoError):
    code, status_code = "invalid_csv", 422


class ProviderError(LeadKhojoError):
    code, status_code = "discovery_provider_failed", 424


class ConflictError(LeadKhojoError):
    code, status_code = "conflict", 409


class ConfigurationError(LeadKhojoError):
    code, status_code = "configuration_error", 500


class CrawlError(LeadKhojoError):
    """We refuse to crawl this target at all (e.g. a private address)."""

    code, status_code = "crawl_refused", 400


class RuleLoadError(LeadKhojoError):
    """A rule pack is malformed. Raised at startup, never mid-scan."""

    code, status_code = "rule_load_failed", 500


class PluginError(LeadKhojoError):
    """A plugin misbehaved. Isolated by the engine; never fails a scan."""

    code, status_code = "plugin_failed", 500
