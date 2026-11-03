import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

from krep.api.errors import ApiError
from krep.auth import crypto
from krep.auth.adapters import AuthAdapter, get_adapter

CACHE_TTL_SECONDS = 60.0

_now: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class ResolvedConfig:
    id: uuid.UUID
    product_id: uuid.UUID | None
    rev: int
    adapter: AuthAdapter
    config: BaseModel
    secrets: Mapping[str, str] = field(repr=False)

    def verify(self, token: str) -> Mapping[str, Any]:
        return self.adapter.verify(token, self.config, self.secrets)


_cache: dict[tuple[uuid.UUID, int], tuple[float, ResolvedConfig]] = {}


def clear_cache() -> None:
    _cache.clear()


def _invalid(message: str, **extra: Any) -> ApiError:
    return ApiError(422, "auth_config_invalid", message, **extra)


def _secret_payload(
    adapter: AuthAdapter, config: Mapping[str, Any], secret: str | None
) -> dict[str, Any]:
    payload = {k: v for k, v in config.items() if k not in adapter.secret_fields}
    if secret is not None and adapter.secret_fields:
        payload[adapter.secret_fields[0]] = secret
    return payload


def _validate(adapter: AuthAdapter, payload: dict[str, Any]) -> BaseModel:
    try:
        return adapter.config_model.model_validate(payload)
    except ValidationError as exc:
        raise _invalid(
            "invalid auth config",
            errors=[
                {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
                for e in exc.errors()
            ],
        ) from None


async def _scope(conn: AsyncConnection, tenant: uuid.UUID) -> None:
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))


async def save_config(
    conn: AsyncConnection,
    tenant: uuid.UUID,
    product: uuid.UUID | None,
    adapter_type: str,
    config: Mapping[str, Any],
    secret: str | None,
    actor: str,
) -> dict[str, Any]:
    try:
        adapter = get_adapter(adapter_type)
    except KeyError:
        raise _invalid("unknown adapter") from None
    model = _validate(adapter, _secret_payload(adapter, config, secret))
    stored = model.model_dump(mode="json", exclude=set(adapter.secret_fields))
    ciphertext, key_id = (None, None) if secret is None else crypto.encrypt(secret)
    await _scope(conn, tenant)
    cur = await conn.execute(
        "INSERT INTO auth_configs (tenant_id, product_id, adapter, config, secret_enc, key_id, updated_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (tenant_id, product_id) DO UPDATE SET adapter = EXCLUDED.adapter, "
        "config = EXCLUDED.config, secret_enc = EXCLUDED.secret_enc, key_id = EXCLUDED.key_id, "
        "rev = auth_configs.rev + 1, enabled = true, updated_by = EXCLUDED.updated_by, updated_at = now() "
        "RETURNING id, product_id, adapter, config, key_id, rev, enabled, updated_by, updated_at",
        (tenant, product, adapter_type, Jsonb(stored), ciphertext, key_id, actor),
    )
    row = await cur.fetchone()
    assert row
    return {
        "id": row[0],
        "product_id": row[1],
        "adapter": row[2],
        "config": row[3],
        "secret_set": row[4] is not None,
        "key_id": row[4],
        "rev": row[5],
        "enabled": row[6],
        "updated_by": row[7],
        "updated_at": row[8],
    }


async def load_effective(
    conn: AsyncConnection, tenant: uuid.UUID, product: uuid.UUID | None
) -> ResolvedConfig | None:
    await _scope(conn, tenant)
    cur = await conn.execute(
        "SELECT id, product_id, adapter, config, secret_enc, key_id, rev, enabled "
        "FROM auth_configs WHERE tenant_id = %s "
        "AND (product_id IS NULL OR product_id = %s) "
        "ORDER BY product_id NULLS LAST LIMIT 1",
        (tenant, product),
    )
    row = await cur.fetchone()
    if row is None or not row[7]:
        return None
    config_id, product_id, adapter_type, config, secret_enc, key_id, rev, _ = row
    cached = _cache.get((config_id, rev))
    if cached is not None and cached[0] > _now():
        return cached[1]
    try:
        adapter = get_adapter(adapter_type)
    except KeyError:
        return None
    secrets: dict[str, str] = {}
    if secret_enc is not None and adapter.secret_fields:
        secrets[adapter.secret_fields[0]] = crypto.decrypt(bytes(secret_enc), key_id)
    model = _validate(adapter, {**config, **secrets})
    resolved = ResolvedConfig(config_id, product_id, rev, adapter, model, secrets)
    _cache[(config_id, rev)] = (_now() + CACHE_TTL_SECONDS, resolved)
    return resolved
