from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from krep.identity.resolve import Caller
from krep.search.query import build_tsquery, expand, normalise

MAX_LIMIT = 50
MAX_OFFSET = 500

_VISIBLE = """
WITH sat AS MATERIALIZED (
  SELECT p.id FROM access_policies p
  WHERE p.tenant_id = %(tenant)s
    AND jsonb_path_match(%(doc)s, p.compiled_path, %(vars)s, true)
), visible AS MATERIALIZED (
  SELECT r.id, r.name, r.search_tsv, r.updated_at
  FROM registry r
  WHERE r.tenant_id = %(tenant)s AND r.status = 'published'
    AND (%(type)s::text IS NULL OR r.type = %(type)s)
    AND (%(tags)s::text[] IS NULL OR r.tags @> %(tags)s)
    AND (r.visibility = 'tenant'
      OR (r.visibility = 'private' AND r.created_by = %(user)s)
      OR (r.visibility = 'restricted' AND r.policy_id IN (SELECT id FROM sat)))
)
"""

_RANKED = (
    _VISIBLE
    + """
, lex AS MATERIALIZED (
  SELECT id, row_number() OVER (ORDER BY rank DESC, id) AS rnk FROM (
    SELECT v.id, ts_rank_cd(v.search_tsv, q) AS rank
    FROM visible v, to_tsquery('english', %(tsq)s) q
    WHERE v.search_tsv @@ q
    ORDER BY rank DESC, v.id LIMIT 50
  ) s
), fuzzy AS MATERIALIZED (
  SELECT id, row_number() OVER (ORDER BY sim DESC, id) AS rnk FROM (
    SELECT v.id, word_similarity(%(q_norm)s, v.name) AS sim
    FROM visible v
    WHERE %(q_norm)s <%% v.name
    ORDER BY sim DESC, v.id LIMIT 50
  ) s
)
SELECT c.id,
       (COALESCE(1.0 / (60 + lex.rnk), 0) + COALESCE(1.0 / (60 + fuzzy.rnk), 0))::float8 AS score
FROM (SELECT id FROM lex UNION SELECT id FROM fuzzy) c
LEFT JOIN lex ON lex.id = c.id LEFT JOIN fuzzy ON fuzzy.id = c.id
ORDER BY score DESC, c.id
LIMIT %(limit)s OFFSET %(offset)s
"""
)

_LISTED = (
    _VISIBLE
    + """
SELECT id, 0::float8 AS score FROM visible
ORDER BY updated_at DESC, id
LIMIT %(limit)s OFFSET %(offset)s
"""
)

_HYDRATE = """
SELECT r.id, r.type, r.slug, r.name, r.description, r.tags, v.version AS current_version
FROM registry r LEFT JOIN registry_versions v ON v.id = r.current_version_id
WHERE r.id = ANY(%s)
"""


@dataclass
class SearchHit:
    id: UUID
    type: str
    slug: str
    name: str
    description: str
    tags: list[str]
    current_version: int | None
    score: float


async def registry_search(
    conn: AsyncConnection,
    caller: Caller,
    *,
    q: str,
    type: str | None = None,
    tags: Sequence[str] | None = None,
    limit: int = 10,
    offset: int = 0,
    groups: Sequence[list[str]] = (),
) -> list[SearchHit]:
    limit = max(0, min(limit, MAX_LIMIT))
    offset = max(0, min(offset, MAX_OFFSET))
    params: dict[str, Any] = {
        "tenant": caller.tenant_id,
        "doc": Jsonb(caller.doc),
        "vars": Jsonb({"tenant_id": str(caller.tenant_id)}),
        "user": caller.user_id,
        "type": type,
        "tags": list(tags) if tags else None,
        "limit": limit,
        "offset": offset,
    }
    listing = not q.strip()
    if not listing:
        q_norm = normalise(q)
        tsq = build_tsquery(expand(q_norm, [list(g) for g in groups]))
        if not q_norm and tsq is None:
            return []
        params |= {"q_norm": q_norm, "tsq": tsq}
        await conn.execute(
            "SELECT set_config('pg_trgm.word_similarity_threshold', '0.3', true)"
        )
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_LISTED if listing else _RANKED, params)
        ranked = await cur.fetchall()
        if not ranked:
            return []
        await cur.execute(_HYDRATE, ([row["id"] for row in ranked],))
        details = {row["id"]: row for row in await cur.fetchall()}
    return [SearchHit(score=row["score"], **details[row["id"]]) for row in ranked]
