from collections.abc import Iterator, Mapping
from typing import Any, ClassVar

import pytest
from psycopg import AsyncConnection
from pydantic import BaseModel

from krep.auth import adapters, get_adapter, list_adapters
from krep.auth.store import load_effective, save_config
from tests.db.test_v2_schema import organization

ConfigModel = type[BaseModel]


class FakeConfig(BaseModel):
    api_key: str
    prefix: str = "fake-"


class FakeAdapter:
    type: ClassVar[str] = "fake"
    config_model: ClassVar[ConfigModel] = FakeConfig
    secret_fields: ClassVar[tuple[str, ...]] = ("api_key",)

    def verify(
        self, token: str, config: BaseModel, secrets: Mapping[str, str]
    ) -> Mapping[str, Any]:
        assert isinstance(config, FakeConfig)
        if token != f"{config.prefix}{secrets['api_key']}":
            raise ValueError("bad")
        return {"sub": "fake-user"}


@pytest.fixture
def fake_adapter() -> Iterator[FakeAdapter]:
    adapter = FakeAdapter()
    adapters.register(adapter)
    yield adapter
    adapters.unregister("fake")


def test_listing_includes_builtin_with_secret_fields():
    listing = {a["type"]: a for a in list_adapters()}
    assert listing["hmac"]["secret_fields"] == ["secret"]
    assert "secret" in listing["hmac"]["config_schema"]["properties"]


def test_unknown_adapter_raises():
    with pytest.raises(KeyError):
        get_adapter("nope")


async def test_v2ac18_fake_adapter_end_to_end(
    owner_conn: AsyncConnection, key_ring: dict[str, str], fake_adapter: FakeAdapter
):
    assert "fake" in {a["type"] for a in list_adapters()}
    tenant = await organization(owner_conn)
    await owner_conn.execute("SET LOCAL ROLE krep_app")
    await save_config(owner_conn, tenant, None, "fake", {"prefix": "p-"}, "k-123", "u")
    resolved = await load_effective(owner_conn, tenant, None)
    assert resolved is not None
    assert resolved.verify("p-k-123") == {"sub": "fake-user"}
    with pytest.raises(ValueError):
        resolved.verify("p-wrong")


async def test_unregistered_adapter_row_fails_closed(
    owner_conn: AsyncConnection, key_ring: dict[str, str]
):
    adapters.register(FakeAdapter())
    tenant = await organization(owner_conn)
    await owner_conn.execute("SET LOCAL ROLE krep_app")
    await save_config(owner_conn, tenant, None, "fake", {}, "k", "u")
    adapters.unregister("fake")
    assert await load_effective(owner_conn, tenant, None) is None
