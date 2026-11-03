import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import psycopg
import pytest
import pytest_asyncio

from krep.api.errors import ApiError
from krep.registry import specs
from krep.registry.links import create_link
from krep.registry.publish import publish
from krep.registry.resources import create_resource
from krep.registry.specs import FieldError
from krep.registry.versions import create_draft, get_version, replace_draft
from krep.search.engine import registry_search
from tests.conftest import alembic, role_url
from tests.registry.conftest import caller_for, new_skill, scalar, share

TOOL_SQL = """
INSERT INTO registry_types VALUES ('tool', 'tools', 'HTTP tool');
CREATE TABLE tools (
  version_id uuid PRIMARY KEY, registry_id uuid NOT NULL, tenant_id uuid NOT NULL,
  type text NOT NULL DEFAULT 'tool' CHECK (type = 'tool'),
  method text NOT NULL, url text NOT NULL,
  input_schema jsonb NOT NULL DEFAULT '{}', output_schema jsonb NOT NULL DEFAULT '{}',
  FOREIGN KEY (version_id, registry_id) REFERENCES registry_versions(id, registry_id) ON DELETE CASCADE,
  FOREIGN KEY (registry_id, type) REFERENCES registry(id, type) ON DELETE CASCADE
);
INSERT INTO link_rules VALUES ('skill', 'tool', 'uses', true, 'source');
CREATE TRIGGER tools_immutable BEFORE UPDATE ON tools
  FOR EACH ROW EXECUTE FUNCTION reject_published_update();
ALTER TABLE tools ENABLE ROW LEVEL SECURITY;
ALTER TABLE tools FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON tools
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON tools TO krep_app;
"""


def validate_tool(spec: dict[str, Any]) -> list[FieldError]:
    errors: list[FieldError] = []
    if spec.get("method") not in {"GET", "POST"}:
        errors.append(FieldError("spec.method", "must be GET or POST"))
    if not isinstance(spec.get("url"), str) or not spec["url"].startswith("https://"):
        errors.append(FieldError("spec.url", "must be an https url"))
    return errors


@pytest.fixture
def tool_db(scratch_db: str) -> Iterator[str]:
    alembic(scratch_db, "upgrade", "head")
    with psycopg.connect(role_url("krep_owner", scratch_db), autocommit=True) as owner:
        owner.execute(TOOL_SQL)  # type: ignore[arg-type]
    yield scratch_db


@pytest.fixture(autouse=True)
def tool_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(specs.VALIDATORS, "tool", validate_tool)


@pytest_asyncio.fixture
async def tconn(tool_db: str) -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(
        role_url("krep_app", tool_db)
    ) as conn:
        yield conn
        await conn.rollback()


@pytest.fixture
def ttenant() -> uuid.UUID:
    return uuid.uuid4()


def tool_body(slug: str = "lookup-order", **extra: Any) -> dict[str, Any]:
    return {
        "type": "tool",
        "slug": slug,
        "name": "Order lookup",
        "description": "Looks up refund order status",
        "tags": ["orders"],
        "spec": {
            "method": "GET",
            "url": "https://orders.example.com/{id}",
            "input_schema": {"type": "object"},
        },
        **extra,
    }


async def test_ac27_new_type_is_created_versioned_published_and_searched(
    tconn: psycopg.AsyncConnection, ttenant: uuid.UUID
) -> None:
    await tconn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(ttenant),))
    caller = caller_for(ttenant)

    created = await create_resource(tconn, caller, tool_body())
    rid = created["id"]
    assert created["type"] == "tool"
    await share(tconn, ttenant, rid)

    v1 = await get_version(tconn, caller, rid, 1)
    assert v1["spec"]["method"] == "GET"
    assert v1["spec"]["input_schema"] == {"type": "object"}
    assert v1["spec"]["output_schema"] == {}
    assert "version_id" not in v1["spec"] and "tenant_id" not in v1["spec"]

    out = await publish(tconn, caller, rid, 1)
    assert out["status"] == "published"

    draft = await create_draft(tconn, caller, rid)
    assert draft["version"]["version"] == 2
    copied = await get_version(tconn, caller, rid, 2)
    assert copied["spec"] == v1["spec"]
    await replace_draft(
        tconn,
        caller,
        rid,
        2,
        spec={"method": "POST", "url": "https://orders.example.com/search"},
    )
    assert (await get_version(tconn, caller, rid, 2))["spec"]["method"] == "POST"
    await publish(tconn, caller, rid, 2)

    hits = await registry_search(
        tconn, caller_for(ttenant, "other"), q="refund", type="tool"
    )
    assert [h.slug for h in hits] == ["lookup-order"]
    assert hits[0].current_version == 2


async def test_ac27_new_type_validator_and_unknown_fields_are_rejected(
    tconn: psycopg.AsyncConnection, ttenant: uuid.UUID
) -> None:
    await tconn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(ttenant),))
    caller = caller_for(ttenant)
    bad = tool_body()
    bad["spec"] = {**bad["spec"], "method": "TRACE"}
    with pytest.raises(ApiError) as exc:
        await create_resource(tconn, caller, bad)
    assert (exc.value.status, exc.value.error) == (422, "validation_failed")
    unknown = tool_body("other-tool")
    unknown["spec"] = {**unknown["spec"], 'evil"; DROP TABLE registry; --': 1}
    with pytest.raises(ApiError) as exc2:
        await create_resource(tconn, caller, unknown)
    assert (exc2.value.status, exc2.value.error) == (422, "validation_failed")
    assert await scalar(tconn, "SELECT count(*) FROM registry") == 0


async def test_ac27_published_new_type_rows_are_immutable(
    tconn: psycopg.AsyncConnection, ttenant: uuid.UUID
) -> None:
    await tconn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(ttenant),))
    caller = caller_for(ttenant)
    rid = (await create_resource(tconn, caller, tool_body()))["id"]
    await publish(tconn, caller, rid, 1)
    with pytest.raises(psycopg.errors.CheckViolation):
        await tconn.execute(
            "UPDATE tools SET method = 'POST' WHERE registry_id = %s", (rid,)
        )


async def test_ac27_new_type_participates_in_links_and_freezing(
    tconn: psycopg.AsyncConnection, ttenant: uuid.UUID
) -> None:
    await tconn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(ttenant),))
    caller = caller_for(ttenant)
    tool = (await create_resource(tconn, caller, tool_body()))["id"]
    skill = await new_skill(tconn, caller)
    await publish(tconn, caller, tool, 1)
    out = await create_link(tconn, caller, skill, tool, "uses", "out", None, True)
    assert out["status"] == "accepted"
    await publish(tconn, caller, skill, 1)
    assert await scalar(tconn, "SELECT count(*) FROM registry_version_deps") == 1
