import os
from dataclasses import dataclass
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

ENV_NAME = "KREP_ENCRYPTION_KEYS"


class CryptoConfigError(RuntimeError):
    pass


class DecryptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Ring:
    primary_id: str
    by_id: dict[str, Fernet]
    multi: MultiFernet


@lru_cache
def _parse(raw: str) -> _Ring:
    if not raw.strip():
        raise CryptoConfigError(f"{ENV_NAME} is not set")
    by_id: dict[str, Fernet] = {}
    for entry in raw.split(","):
        key_id, sep, key = entry.strip().partition(":")
        if not sep or not key_id or key_id in by_id:
            raise CryptoConfigError(
                f"{ENV_NAME} must be a comma list of unique <key_id>:<key> entries"
            )
        try:
            by_id[key_id] = Fernet(key.encode())
        except ValueError:
            raise CryptoConfigError(
                f"{ENV_NAME} key {key_id!r} is not a valid key"
            ) from None
    return _Ring(next(iter(by_id)), by_id, MultiFernet(list(by_id.values())))


def _ring() -> _Ring:
    return _parse(os.environ.get(ENV_NAME, ""))


def validate() -> None:
    _ring()


def encrypt(plaintext: str) -> tuple[bytes, str]:
    ring = _ring()
    return ring.multi.encrypt(plaintext.encode()), ring.primary_id


def decrypt(ciphertext: bytes, key_id: str) -> str:
    fernet = _ring().by_id.get(key_id)
    if fernet is None:
        raise DecryptionError("unknown key id")
    try:
        return fernet.decrypt(ciphertext).decode()
    except InvalidToken:
        raise DecryptionError("cannot decrypt secret") from None
