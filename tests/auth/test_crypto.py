import pytest

from krep.auth import crypto
from tests.auth.conftest import keys_env, make_key


def test_round_trip(key_ring: dict[str, str]):
    ciphertext, key_id = crypto.encrypt("s3cret-value")
    assert key_id == "k1"
    assert b"s3cret-value" not in ciphertext
    assert crypto.decrypt(ciphertext, key_id) == "s3cret-value"


def test_ciphertext_differs_per_call(key_ring: dict[str, str]):
    assert crypto.encrypt("same")[0] != crypto.encrypt("same")[0]


def test_wrong_key_fails(monkeypatch: pytest.MonkeyPatch, key_ring: dict[str, str]):
    ciphertext, key_id = crypto.encrypt("value")
    monkeypatch.setenv("KREP_ENCRYPTION_KEYS", keys_env(("k1", make_key())))
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(ciphertext, key_id)
    monkeypatch.setenv("KREP_ENCRYPTION_KEYS", keys_env(("k2", make_key())))
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(ciphertext, key_id)


def test_v2ac5_rotation_keeps_old_ciphertext_readable(
    monkeypatch: pytest.MonkeyPatch, key_ring: dict[str, str]
):
    old_ciphertext, old_id = crypto.encrypt("value")
    monkeypatch.setenv(
        "KREP_ENCRYPTION_KEYS",
        keys_env(("k2", make_key()), ("k1", key_ring["k1"])),
    )
    assert crypto.decrypt(old_ciphertext, old_id) == "value"
    new_ciphertext, new_id = crypto.encrypt("value")
    assert new_id == "k2"
    assert crypto.decrypt(new_ciphertext, new_id) == "value"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "nocolon",
        "k1:not-a-fernet-key",
        f"k1:{make_key()},k1:{make_key()}",
        f":{make_key()}",
        f"k1:{make_key()},",
    ],
)
def test_malformed_key_list_rejected(monkeypatch: pytest.MonkeyPatch, raw: str):
    monkeypatch.setenv("KREP_ENCRYPTION_KEYS", raw)
    with pytest.raises(crypto.CryptoConfigError):
        crypto.validate()
    with pytest.raises(crypto.CryptoConfigError):
        crypto.encrypt("value")


def test_missing_key_list_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("KREP_ENCRYPTION_KEYS", raising=False)
    with pytest.raises(crypto.CryptoConfigError):
        crypto.validate()
