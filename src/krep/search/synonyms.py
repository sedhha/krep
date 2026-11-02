import re
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from krep.api.errors import ApiError
from krep.identity.resolve import Caller
from krep.registry.limits import get_limit

MIN_TERMS = 2
MAX_TERMS = 10
MAX_WORDS = 3
CACHE_TTL_SECONDS = 60

_TERM = re.compile(r"[^\W_]+( [^\W_]+)*")

_ROWS = (
    "SELECT id, terms FROM search_synonyms WHERE tenant_id = %s ORDER BY created_at, id"
)
_SAME_SET = (
    "SELECT 1 FROM search_synonyms "
    "WHERE tenant_id = %(tenant)s AND terms @> %(terms)s AND terms <@ %(terms)s "
    "AND id IS DISTINCT FROM %(self)s"
)


class SynonymCache:
    def __init__(
        self,
        ttl: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._clock = clock
        self._entries: dict[UUID, tuple[float, list[list[str]]]] = {}

    async def get(self, conn: AsyncConnection, tenant_id: UUID) -> list[list[str]]:
        entry = self._entries.get(tenant_id)
        if entry is not None and entry[0] > self._clock():
            return entry[1]
        cur = await conn.execute(_ROWS, (tenant_id,))
        groups = [list(terms) for _, terms in await cur.fetchall()]
        self._entries[tenant_id] = (self._clock() + self._ttl, groups)
        return groups

    def invalidate(self, tenant_id: UUID) -> None:
        self._entries.pop(tenant_id, None)


DEFAULT_CACHE = SynonymCache()


def _cache(cache: SynonymCache | None) -> SynonymCache:
    return cache if cache is not None else DEFAULT_CACHE


def _invalid(message: str) -> ApiError:
    return ApiError(
        422,
        "validation_failed",
        "request validation failed",
        errors=[{"field": "terms", "message": message}],
    )


def normalise_terms(terms: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(" ".join(term.lower().split()) for term in terms))
    for term in cleaned:
        if not _TERM.fullmatch(term):
            raise _invalid("terms may only contain letters, digits and spaces")
        if len(term.split()) > MAX_WORDS:
            raise _invalid(f"a term may have at most {MAX_WORDS} words")
    if not MIN_TERMS <= len(cleaned) <= MAX_TERMS:
        raise _invalid(f"a group needs {MIN_TERMS} to {MAX_TERMS} distinct terms")
    return cleaned


async def groups_for(
    conn: AsyncConnection, tenant_id: UUID, cache: SynonymCache | None = None
) -> list[list[str]]:
    return await _cache(cache).get(conn, tenant_id)


async def list_groups(conn: AsyncConnection, tenant_id: UUID) -> list[dict[str, Any]]:
    cur = await conn.execute(_ROWS, (tenant_id,))
    return [{"id": id_, "terms": list(terms)} for id_, terms in await cur.fetchall()]


async def _reject_duplicate(
    conn: AsyncConnection, tenant_id: UUID, terms: list[str], self_id: UUID | None
) -> None:
    cur = await conn.execute(
        _SAME_SET, {"tenant": tenant_id, "terms": terms, "self": self_id}
    )
    if await cur.fetchone() is not None:
        raise ApiError(
            409, "synonym_group_exists", "a group with these terms already exists"
        )


async def create_group(
    conn: AsyncConnection,
    caller: Caller,
    terms: list[str],
    cache: SynonymCache | None = None,
) -> dict[str, Any]:
    cleaned = normalise_terms(terms)
    await _reject_duplicate(conn, caller.tenant_id, cleaned, None)
    limit = await get_limit(conn, tenant_id=caller.tenant_id, key="max_synonym_groups")
    cur = await conn.execute(
        "SELECT count(*) FROM search_synonyms WHERE tenant_id = %s", (caller.tenant_id,)
    )
    row = await cur.fetchone()
    assert row is not None
    if row[0] >= limit:
        raise ApiError(
            409, "synonym_limit_reached", "synonym group limit reached", limit=limit
        )
    cur = await conn.execute(
        "INSERT INTO search_synonyms (tenant_id, terms, created_by) VALUES (%s, %s, %s) "
        "RETURNING id",
        (caller.tenant_id, cleaned, caller.user_id),
    )
    row = await cur.fetchone()
    assert row is not None
    _cache(cache).invalidate(caller.tenant_id)
    return {"id": row[0], "terms": cleaned}


async def update_group(
    conn: AsyncConnection,
    tenant_id: UUID,
    group_id: UUID,
    terms: list[str],
    cache: SynonymCache | None = None,
) -> dict[str, Any]:
    cleaned = normalise_terms(terms)
    await _reject_duplicate(conn, tenant_id, cleaned, group_id)
    cur = await conn.execute(
        "UPDATE search_synonyms SET terms = %s WHERE tenant_id = %s AND id = %s RETURNING id",
        (cleaned, tenant_id, group_id),
    )
    if await cur.fetchone() is None:
        raise ApiError(404, "not_found", "synonym group not found")
    _cache(cache).invalidate(tenant_id)
    return {"id": group_id, "terms": cleaned}


async def delete_group(
    conn: AsyncConnection,
    tenant_id: UUID,
    group_id: UUID,
    cache: SynonymCache | None = None,
) -> None:
    cur = await conn.execute(
        "DELETE FROM search_synonyms WHERE tenant_id = %s AND id = %s RETURNING id",
        (tenant_id, group_id),
    )
    if await cur.fetchone() is None:
        raise ApiError(404, "not_found", "synonym group not found")
    _cache(cache).invalidate(tenant_id)
