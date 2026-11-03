import pytest
from cryptography.fernet import Fernet

from krep.cli import main


def test_keys_generate_prints_key_id_and_fernet_key(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("KREP_MIGRATION_DATABASE_URL", raising=False)
    assert main(["keys", "generate", "--id", "k9"]) == 0
    key_id, _, key = capsys.readouterr().out.strip().partition(":")
    assert key_id == "k9"
    Fernet(key.encode())


def test_keys_generate_default_id(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("KREP_MIGRATION_DATABASE_URL", raising=False)
    assert main(["keys", "generate"]) == 0
    key_id, _, key = capsys.readouterr().out.strip().partition(":")
    assert key_id.startswith("k")
    Fernet(key.encode())
