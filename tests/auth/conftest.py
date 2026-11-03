import os

import pytest
from cryptography.fernet import Fernet

from krep.auth.store import clear_cache


def make_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def key_ring(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    ring = {"k1": make_key(), "k0": make_key()}
    monkeypatch.setenv("KREP_ENCRYPTION_KEYS", f"k1:{ring['k1']}")
    return ring


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    clear_cache()


def keys_env(*pairs: tuple[str, str]) -> str:
    return ",".join(f"{key_id}:{key}" for key_id, key in pairs)


__all__ = ["keys_env", "make_key", "key_ring", "os"]
