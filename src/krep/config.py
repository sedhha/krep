import os
from dataclasses import dataclass
from functools import lru_cache


def _flag(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    migration_database_url: str
    search_semantic_enabled: bool = False
    search_log_zero_results: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ["KREP_DATABASE_URL"],
        migration_database_url=os.environ.get("KREP_MIGRATION_DATABASE_URL", ""),
        search_semantic_enabled=_flag("KREP_SEARCH_SEMANTIC_ENABLED"),
        search_log_zero_results=_flag("KREP_SEARCH_LOG_ZERO_RESULTS"),
    )
