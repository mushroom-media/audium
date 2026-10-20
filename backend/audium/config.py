"""All runtime configuration, read from AUDIUM_* environment variables.

Every option is documented in docs/configuration.md; keep both in sync.
"""

from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUDIUM_", extra="ignore")

    # Paths
    data_dir: Path = Path("/data")
    music_dir: Path = Path("/music")
    database_url: str | None = None

    # HTTP
    host: str = "0.0.0.0"
    port: int = 8080
    base_path: str = ""
    trusted_proxies: str = "127.0.0.1"
    cookie_secure: Literal["auto", "true", "false"] = "auto"
    access_log: bool = False

    # Logging
    log_level: str = "info"
    log_format: Literal["json", "console"] = "json"

    # Auth
    session_ttl_days: int = 30
    admin_user: str | None = None
    admin_password: str | None = None
    login_max_attempts: int = 10
    login_window_minutes: int = 15

    # Library / scanner
    library_roots: str | None = None
    scan_on_start: bool = True
    scan_interval_minutes: int = 360
    scan_workers: int = 4
    missing_grace_days: int = 7
    ignored_articles: str = "The El La Los Las Le Les Os As O A"

    @field_validator("base_path")
    @classmethod
    def _normalize_base_path(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if v and not v.startswith("/"):
            v = "/" + v
        return v

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'audium.db'}"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @cached_property
    def articles(self) -> tuple[str, ...]:
        return tuple(a.casefold() for a in self.ignored_articles.split() if a)
