import logging
import uuid
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from prometheus_client import REGISTRY

from krep.api import create_app
from krep.api import search as search_api
from krep.api.deps import get_caller
from krep.api.errors import install_error_handlers
from krep.api.search import router
from krep.config import Settings
from krep.identity.resolve import Caller
from krep.search import synonyms
from tests.api.conftest import OwnerExec, Pool

MakeSearchClient = Callable[..., httpx.AsyncClient]


def zero_results(tenant: str) -> float:
    return (
        REGISTRY.get_sample_value("search_zero_results_total", {"tenant": tenant})
        or 0.0
    )


@pytest.fixture
def make_search_client(pool: Pool) -> MakeSearchClient:
    def make(
        tenant: uuid.UUID, admin: bool = False, user: str = "u1"
    ) -> httpx.AsyncClient:
        app = FastAPI()
        app.state.pool = pool
        install_error_handlers(app)
        app.include_router(router)

        async def caller() -> Caller:
            return Caller(tenant, user, {"token": {}, "principal": {}}, admin, admin)

        app.dependency_overrides[get_caller] = caller
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        )

    return make


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    set_log_flag(monkeypatch, False)
    monkeypatch.setattr(synonyms, "DEFAULT_CACHE", synonyms.SynonymCache())


async def add(
    owner_exec: OwnerExec,
    tenant: uuid.UUID,
    slug: str,
    name: str,
    description: str = "",
) -> None:
    await owner_exec(
        "INSERT INTO access_policies (tenant_id, name, ast, source, compiled_path, "
        "compiler_version, reserved, kind, created_by, updated_by) "
        "VALUES (%s, 'open-to-all', '{}'::jsonb, 'true', 'true'::jsonpath, 1, true, 'open', "
        "'t', 't') ON CONFLICT (tenant_id, name) DO NOTHING",
        (tenant,),
    )
    await owner_exec(
        "WITH r AS (INSERT INTO registry (tenant_id, type, slug, name, description, tags, "
        "status, created_by, updated_by) "
        "VALUES (%s, 'agent', %s, %s, %s, ARRAY['billing'], 'published', 'u1', 'u1') "
        "RETURNING id, tenant_id) "
        "INSERT INTO registry_policies (registry_id, tenant_id, action, policy_id) "
        "SELECT r.id, r.tenant_id, 'read', p.id FROM r "
        "JOIN access_policies p ON p.tenant_id = r.tenant_id AND p.name = 'open-to-all'",
        (tenant, slug, name, description),
    )


def test_search_route_registered_before_resource_id_route() -> None:
    paths = list(create_app().openapi()["paths"])
    assert paths.index("/v1/registry/search") < paths.index(
        "/v1/registry/{resource_id}"
    )


async def test_ac6_response_shape_has_no_total_and_next_page_is_empty(
    make_search_client: MakeSearchClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await add(
        owner_exec, tenant_id, "refund-assistant", "Refund Assistant", "Handles refunds"
    )
    async with make_search_client(tenant_id) as c:
        body = (await c.get("/v1/registry/search", params={"q": "refund"})).json()
        assert set(body) == {"items", "limit", "offset"}
        assert (body["limit"], body["offset"]) == (10, 0)
        item = body["items"][0]
        assert set(item) == {
            "id",
            "type",
            "slug",
            "name",
            "description",
            "tags",
            "current_version",
            "score",
        }
        assert item["slug"] == "refund-assistant"
        page2 = (
            await c.get("/v1/registry/search", params={"q": "refund", "offset": 10})
        ).json()
        assert page2["items"] == []


async def test_search_filters_by_type_and_tags(
    make_search_client: MakeSearchClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await add(owner_exec, tenant_id, "alpha", "Refund Agent")
    async with make_search_client(tenant_id) as c:
        ok = await c.get(
            "/v1/registry/search",
            params={"q": "refund", "type": "agent", "tags": "billing"},
        )
        assert len(ok.json()["items"]) == 1
        wrong_tag = await c.get(
            "/v1/registry/search", params={"q": "refund", "tags": "billing,other"}
        )
        assert wrong_tag.json()["items"] == []
        wrong_type = await c.get(
            "/v1/registry/search", params={"q": "refund", "type": "skill"}
        )
        assert wrong_type.json()["items"] == []


async def test_empty_query_lists_visible_resources(
    make_search_client: MakeSearchClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await add(owner_exec, tenant_id, "alpha", "Alpha")
    async with make_search_client(tenant_id) as c:
        items = (await c.get("/v1/registry/search")).json()["items"]
        assert [i["slug"] for i in items] == ["alpha"]


@pytest.mark.parametrize(
    "params",
    [{"limit": 51}, {"limit": 0}, {"offset": 501}, {"offset": -1}, {"limit": "x"}],
)
async def test_search_param_bounds(
    make_search_client: MakeSearchClient,
    tenant_id: uuid.UUID,
    params: dict[str, str | int],
) -> None:
    async with make_search_client(tenant_id) as c:
        res = await c.get("/v1/registry/search", params=params)
        assert res.status_code == 422
        assert res.json()["error"] == "validation_failed"


async def test_search_param_maxima_accepted(
    make_search_client: MakeSearchClient, tenant_id: uuid.UUID
) -> None:
    async with make_search_client(tenant_id) as c:
        res = await c.get("/v1/registry/search", params={"limit": 50, "offset": 500})
        assert res.status_code == 200


async def test_ac24_synonym_api_roundtrip_affects_search_immediately(
    make_search_client: MakeSearchClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await add(owner_exec, tenant_id, "res", "Billing Agent", "Handles refund requests")
    async with make_search_client(tenant_id, admin=True) as c:
        search = lambda: c.get("/v1/registry/search", params={"q": "reimbursement"})  # noqa: E731
        assert (await search()).json()["items"] == []
        created = await c.post(
            "/v1/search/synonyms",
            json={"terms": ["Refund", "money back", "reimbursement"]},
        )
        assert created.status_code == 201
        group = created.json()
        assert group["terms"] == ["refund", "money back", "reimbursement"]
        assert len((await search()).json()["items"]) == 1
        assert (await c.get("/v1/search/synonyms")).json()["items"] == [group]
        updated = await c.put(
            f"/v1/search/synonyms/{group['id']}", json={"terms": ["a1", "b1"]}
        )
        assert updated.status_code == 200
        assert (await search()).json()["items"] == []
        assert (await c.delete(f"/v1/search/synonyms/{group['id']}")).status_code == 204
        assert (await c.get("/v1/search/synonyms")).json()["items"] == []


async def test_synonym_errors(
    make_search_client: MakeSearchClient, tenant_id: uuid.UUID
) -> None:
    async with make_search_client(tenant_id, admin=True) as c:
        bad = await c.post("/v1/search/synonyms", json={"terms": ["solo"]})
        assert (bad.status_code, bad.json()["error"]) == (422, "validation_failed")
        missing = await c.post("/v1/search/synonyms", json={})
        assert missing.status_code == 422
        assert (
            await c.post("/v1/search/synonyms", json={"terms": ["a1", "b1"]})
        ).status_code == 201
        dup = await c.post("/v1/search/synonyms", json={"terms": ["b1", "a1"]})
        assert (dup.status_code, dup.json()["error"]) == (409, "synonym_group_exists")
        gone = await c.delete(f"/v1/search/synonyms/{uuid.uuid4()}")
        assert gone.status_code == 404


async def test_synonym_endpoints_forbidden_for_non_admin(
    make_search_client: MakeSearchClient, tenant_id: uuid.UUID
) -> None:
    async with make_search_client(tenant_id, admin=False) as c:
        gid = uuid.uuid4()
        responses = [
            await c.get("/v1/search/synonyms"),
            await c.post("/v1/search/synonyms", json={"terms": ["a1", "b1"]}),
            await c.put(f"/v1/search/synonyms/{gid}", json={"terms": ["a1", "b1"]}),
            await c.delete(f"/v1/search/synonyms/{gid}"),
        ]
        assert [r.status_code for r in responses] == [403] * 4


async def test_ac26_zero_results_counted_for_that_tenant_only(
    make_search_client: MakeSearchClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    other = uuid.uuid4()
    await add(owner_exec, tenant_id, "alpha", "Refund Agent")
    async with make_search_client(tenant_id) as c, make_search_client(other) as o:
        await c.get("/v1/registry/search", params={"q": "refund"})
        assert zero_results(str(tenant_id)) == 0
        await c.get("/v1/registry/search", params={"q": "nonexistentterm"})
        assert zero_results(str(tenant_id)) == 1
        assert zero_results(str(other)) == 0
        await o.get("/v1/registry/search", params={"q": "refund"})
        assert zero_results(str(other)) == 1
        assert zero_results(str(tenant_id)) == 1


async def test_ac26_empty_listing_and_later_pages_are_not_missed_searches(
    make_search_client: MakeSearchClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await add(owner_exec, tenant_id, "alpha", "Refund Agent")
    async with make_search_client(tenant_id) as c:
        await c.get("/v1/registry/search", params={"q": "refund", "offset": 10})
        await c.get("/v1/registry/search", params={"type": "skill"})
        assert zero_results(str(tenant_id)) == 0


def set_log_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    settings = Settings(
        database_url="", migration_database_url="", search_log_zero_results=enabled
    )
    monkeypatch.setattr(search_api, "get_settings", lambda: settings)


async def test_ac26_query_not_logged_by_default(
    make_search_client: MakeSearchClient,
    tenant_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    set_log_flag(monkeypatch, False)
    with caplog.at_level(logging.DEBUG, logger="krep"):
        async with make_search_client(tenant_id) as c:
            await c.get("/v1/registry/search", params={"q": "Secret Words"})
    assert "secret words" not in caplog.text.lower()
    assert "Secret" not in caplog.text


async def test_ac26_normalised_query_logged_when_enabled_and_capped(
    make_search_client: MakeSearchClient,
    tenant_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    set_log_flag(monkeypatch, True)
    with caplog.at_level(logging.INFO, logger="krep.search"):
        async with make_search_client(tenant_id) as c:
            await c.get(
                "/v1/registry/search", params={"q": "  Secret,   Words! " + "z" * 300}
            )
    records = [r for r in caplog.records if r.name == "krep.search"]
    assert len(records) == 1
    logged = records[0].__dict__["query"]
    assert logged.startswith("secret words zzz")
    assert len(logged) <= 100
