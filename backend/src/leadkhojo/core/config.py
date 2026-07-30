"""Application configuration.

Every environment variable in the system is declared here and validated at
boot. Nothing else in the codebase reads os.environ — a missing variable must
fail loudly at startup, not three minutes into someone's scan.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- application -------------------------------------------------------
    environment: str = "local"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # -- database ----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://leadkhojo:leadkhojo@localhost:5432/leadkhojo"

    # -- server ------------------------------------------------------------
    # Bind to loopback by default. v1 has no authentication; an instance
    # reachable from the internet lets anyone run scans from your IP.
    host: str = "127.0.0.1"
    port: int = 8000

    # -- crawler -----------------------------------------------------------
    user_agent: str = "LeadKhojoBot/1.0 (+https://leadkhojo.com/bot)"
    max_pages_per_site: int = 8
    request_timeout_seconds: float = 15.0
    connect_timeout_seconds: float = 5.0
    site_budget_seconds: float = 60.0
    max_redirects: int = 5
    max_concurrent_sites: int = 10
    host_delay_seconds: float = 1.0
    max_page_bytes: int = 5 * 1024 * 1024
    enable_playwright: bool = False
    render_min_text_chars: int = 500

    # -- rules -------------------------------------------------------------
    rules_dir: Path = _REPO_ROOT / "rules"

    # -- plugins -----------------------------------------------------------
    disabled_plugins: tuple[str, ...] = ()

    # -- opportunities -----------------------------------------------------
    # AI rewriting is OFF by default and may only ever rephrase text the rule
    # engine already produced. See docs/03-ARCHITECTURE.md section 9.3.
    enable_ai_rewrite: bool = False
    anthropic_api_key: SecretStr | None = None

    # -- discovery ---------------------------------------------------------
    discovery_provider: str = "csv_import"
    google_places_api_key: SecretStr | None = None
    google_places_cache_days: int = 30

    # -- export ------------------------------------------------------------
    export_dir: Path = Field(default_factory=lambda: Path.cwd() / "exports")

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @property
    def binds_publicly(self) -> bool:
        return self.host in ("0.0.0.0", "::", "")  # noqa: S104

    @property
    def ai_rewrite_available(self) -> bool:
        """AI rewriting requires an explicit opt-in AND a key.

        Absent either, the deterministic description is used. AI is never on
        the critical path.
        """
        return self.enable_ai_rewrite and self.anthropic_api_key is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
