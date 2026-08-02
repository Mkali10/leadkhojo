"""Configuration.

Two things are being protected here.

The first is that configuration is the only way to change behaviour: nothing
in the codebase reads the environment except config.py, and nothing hardcodes
a value that an operator would reasonably want to change.

The second is that the defaults are the safe ones. Someone who runs this with
an empty .env must get the polite, loopback-bound, no-AI, no-Playwright
configuration — not because they read the documentation, but because that is
what happens by default.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from leadkhojo.core.config import Settings, get_settings

ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def _defaults() -> Settings:
    """Settings with no .env and no environment influence."""
    return Settings(_env_file=None)  # type: ignore[call-arg]


# ---------------------------------------------------------------- safe defaults


def test_the_server_binds_to_loopback_by_default() -> None:
    """v1 has no authentication. A default of 0.0.0.0 would turn a local
    tool into an open scanning proxy on someone's first run."""
    settings = _defaults()

    assert settings.host == "127.0.0.1"
    assert settings.binds_publicly is False


@pytest.mark.parametrize("host", ["0.0.0.0", "::", ""])
def test_a_public_bind_is_detected(host: str) -> None:
    """The app logs a warning on this. It cannot warn about what it cannot
    detect."""
    assert Settings(_env_file=None, host=host).binds_publicly is True  # type: ignore[call-arg]


def test_ai_rewriting_is_off_by_default() -> None:
    settings = _defaults()

    assert settings.enable_ai_rewrite is False
    assert settings.ai_rewrite_available is False


def test_ai_rewriting_needs_both_the_flag_and_a_key() -> None:
    """Either alone is a misconfiguration, and a misconfiguration must fall
    back to the deterministic text rather than half-enable a model."""
    flag_only = Settings(_env_file=None, enable_ai_rewrite=True)  # type: ignore[call-arg]
    key_only = Settings(_env_file=None, anthropic_api_key="sk-test")  # type: ignore[call-arg]
    both = Settings(  # type: ignore[call-arg]
        _env_file=None, enable_ai_rewrite=True, anthropic_api_key="sk-test"
    )

    assert flag_only.ai_rewrite_available is False
    assert key_only.ai_rewrite_available is False
    assert both.ai_rewrite_available is True


def test_the_user_agent_is_honest_and_contactable() -> None:
    """Pretending to be Chrome is the difference between a crawler and an
    intruder. The default must identify us and say where to complain."""
    user_agent = _defaults().user_agent

    assert "LeadKhojoBot" in user_agent
    assert "http" in user_agent
    for browser in ("Mozilla", "Chrome", "Safari", "Gecko"):
        assert browser not in user_agent


def test_the_crawler_defaults_are_polite() -> None:
    settings = _defaults()

    assert settings.host_delay_seconds >= 1.0
    assert settings.max_pages_per_site <= 10
    assert settings.request_timeout_seconds <= 30


def test_playwright_is_off_by_default() -> None:
    """It costs roughly 20x an HTTP fetch."""
    assert _defaults().enable_playwright is False


# ---------------------------------------------------------------- env parsing


def test_every_setting_can_be_overridden_by_an_env_var(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LK_HOST", "10.0.0.5")
    monkeypatch.setenv("LK_PORT", "9001")
    monkeypatch.setenv("LK_MAX_PAGES_PER_SITE", "3")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.host == "10.0.0.5"
    assert settings.port == 9001
    assert settings.max_pages_per_site == 3


def test_the_prefix_is_required(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """An unprefixed HOST belongs to something else on the machine."""
    monkeypatch.setenv("HOST", "10.0.0.5")

    assert Settings(_env_file=None).host == "127.0.0.1"  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("performance,cms", ("performance", "cms")),
        ("performance, cms", ("performance", "cms")),
        (" performance ", ("performance",)),
        ("", ()),
    ],
)
def test_list_settings_accept_the_spelling_a_human_uses(
    monkeypatch, raw: str, expected: tuple[str, ...]
) -> None:  # type: ignore[no-untyped-def]
    """pydantic-settings decodes tuple fields as JSON by default, which makes
    the obvious `.env` spelling a startup crash. It is documented as
    comma-separated, so it has to work that way."""
    monkeypatch.setenv("LK_DISABLED_PLUGINS", raw)

    assert Settings(_env_file=None).disabled_plugins == expected  # type: ignore[call-arg]


def test_cors_origins_are_comma_separated_too(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LK_CORS_ORIGINS", "http://a.test,http://b.test")

    assert Settings(_env_file=None).cors_origins == (  # type: ignore[call-arg]
        "http://a.test",
        "http://b.test",
    )


def test_the_log_level_is_case_insensitive(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LK_LOG_LEVEL", "debug")

    assert Settings(_env_file=None).log_level == "DEBUG"  # type: ignore[call-arg]


def test_an_unknown_variable_is_ignored_not_fatal(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A stale LK_ variable in someone's shell must not stop the server."""
    monkeypatch.setenv("LK_SOMETHING_WE_REMOVED", "1")

    assert Settings(_env_file=None).host == "127.0.0.1"  # type: ignore[call-arg]


# ---------------------------------------------------------------- secrets


def test_api_keys_are_secrets_that_do_not_print() -> None:
    """Settings end up in log lines and crash reports. A key that renders as
    itself is a key that leaks."""
    settings = Settings(_env_file=None, anthropic_api_key="sk-ant-real-key")  # type: ignore[call-arg]

    assert "sk-ant-real-key" not in repr(settings)
    assert "sk-ant-real-key" not in str(settings)
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-real-key"


def test_no_secret_has_a_default_value() -> None:
    """A hardcoded fallback credential is the one people forget to override."""
    settings = _defaults()

    assert settings.anthropic_api_key is None
    assert settings.google_places_api_key is None


# ---------------------------------------------------------------- drift


def test_env_example_documents_every_setting() -> None:
    """The file is the operator's only map. A setting missing from it is a
    setting nobody knows exists."""
    documented = set(re.findall(r"^#?\s*(LK_[A-Z0-9_]+)=", ENV_EXAMPLE.read_text("utf-8"), re.M))
    expected = {f"LK_{name.upper()}" for name in Settings.model_fields}

    missing = sorted(expected - documented)
    assert not missing, f"Undocumented in .env.example: {', '.join(missing)}"


def test_env_example_invents_no_settings() -> None:
    """The other direction: a variable documented but not read is a setting
    someone will set and quietly wonder why nothing happened."""
    documented = set(re.findall(r"^#?\s*(LK_[A-Z0-9_]+)=", ENV_EXAMPLE.read_text("utf-8"), re.M))
    expected = {f"LK_{name.upper()}" for name in Settings.model_fields}

    unread = sorted(documented - expected)
    assert not unread, f"Documented but never read: {', '.join(unread)}"


def test_get_settings_is_cached() -> None:
    """It is called per request. Re-reading and re-validating the environment
    on every one would be a silly cost."""
    assert get_settings() is get_settings()
