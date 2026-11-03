import os
from dataclasses import dataclass
from functools import lru_cache


def _flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    migration_database_url: str
    platform_database_url: str = ""
    search_semantic_enabled: bool = False
    search_log_zero_results: bool = False
    metrics_token: str = ""
    encryption_keys: str = ""
    platform_admin_key: str = ""
    login_issuer: str = ""
    login_jwks_url: str = ""
    login_audience: str = ""
    env: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ["KREP_DATABASE_URL"],
        migration_database_url=os.environ.get("KREP_MIGRATION_DATABASE_URL", ""),
        platform_database_url=os.environ.get("KREP_PLATFORM_DATABASE_URL", ""),
        search_semantic_enabled=_flag("KREP_SEARCH_SEMANTIC_ENABLED"),
        search_log_zero_results=_flag("KREP_SEARCH_LOG_ZERO_RESULTS"),
        metrics_token=os.environ.get("KREP_METRICS_TOKEN", ""),
        encryption_keys=os.environ.get("KREP_ENCRYPTION_KEYS", ""),
        platform_admin_key=os.environ.get("KREP_PLATFORM_ADMIN_KEY", ""),
        login_issuer=os.environ.get("KREP_LOGIN_ISSUER", ""),
        login_jwks_url=os.environ.get("KREP_LOGIN_JWKS_URL", ""),
        login_audience=os.environ.get("KREP_LOGIN_AUDIENCE", ""),
        env=os.environ.get("KREP_ENV", ""),
    )
