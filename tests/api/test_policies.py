import uuid
from typing import Any

import httpx

from tests.api.conftest import MakeClient, OwnerExec

RULE = 'token.department == "billing" && "manager" in token.roles'
BASE = "/v1/access-policies"


async def create(
    client: httpx.AsyncClient, name: str = "p1", rule: str = RULE, **extra: Any
) -> dict[str, Any]:
    r = await client.post(BASE, json={"name": name, "source": rule, **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def test_ac11_create_from_source_and_ast_are_identical(client: httpx.AsyncClient) -> None:
    from_source = await create(client, "a")
    r = await client.post(BASE, json={"name": "b", "ast": from_source["ast"]})
    assert r.status_code == 201
    from_ast = r.json()
    for key in ("source", "compiled_path", "summary"):
        assert from_ast[key] == from_source[key]
    assert from_source["rev"] == 1
    assert from_source["usage_count"] == 0
    assert from_source["warnings"] == []


async def test_create_requires_exactly_one_of_source_and_ast(client: httpx.AsyncClient) -> None:
    neither = await client.post(BASE, json={"name": "x"})
    both = await client.post(BASE, json={"name": "x", "source": RULE, "ast": {}})
    assert neither.status_code == both.status_code == 422
    assert neither.json()["error"] == "validation_failed"


async def test_create_parse_error_reports_line_and_column(client: httpx.AsyncClient) -> None:
    r = await client.post(BASE, json={"name": "x", "source": 'token.a == '})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "policy_parse_error"
    assert isinstance(body["line"], int) and isinstance(body["column"], int)


async def test_create_too_large_reports_nodes_and_max(client: httpx.AsyncClient) -> None:
    rule = " && ".join(f'token.k{i} == "v"' for i in range(150))
    r = await client.post(BASE, json={"name": "x", "source": rule})
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "policy_too_large"
    assert body["max"] == 100 and body["nodes"] > 100


async def test_create_invalid_ast_is_422(client: httpx.AsyncClient) -> None:
    r = await client.post(BASE, json={"name": "x", "ast": {"op": "nope"}})
    assert r.status_code == 422
    assert r.json()["error"] == "policy_invalid"


async def test_create_duplicate_name_conflicts(client: httpx.AsyncClient) -> None:
    await create(client, "dup")
    r = await client.post(BASE, json={"name": "dup", "source": RULE})
    assert r.status_code == 409
    assert r.json()["error"] == "policy_name_taken"


async def test_get_returns_full_view(client: httpx.AsyncClient) -> None:
    created = await create(client, "g", description="d")
    r = await client.get(f"{BASE}/{created['id']}")
    assert r.status_code == 200
    body = r.json()
    for key in ("ast", "source", "compiled_path", "rev", "summary", "usage_count"):
        assert key in body
    assert body["description"] == "d"


async def test_list_returns_created_policies(client: httpx.AsyncClient) -> None:
    await create(client, "l1")
    await create(client, "l2", 'token.a == "x"')
    r = await client.get(BASE)
    assert r.status_code == 200
    assert {i["name"] for i in r.json()["items"]} == {"l1", "l2"}


async def test_ac11_put_bumps_rev_and_regenerates_source(client: httpx.AsyncClient) -> None:
    created = await create(client, "u")
    r = await client.put(
        f"{BASE}/{created['id']}",
        json={"name": "u2", "description": "new", "source": 'token.a  ==  "x"', "rev": 1},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["rev"] == 2
    assert body["name"] == "u2"
    assert body["description"] == "new"
    assert body["source"] == 'token.a == "x"'
    assert body["compiled_path"] != created["compiled_path"]


async def test_ac11_stale_rev_returns_rev_conflict(client: httpx.AsyncClient) -> None:
    created = await create(client, "c")
    path = f"{BASE}/{created['id']}"
    ok = await client.put(path, json={"name": "c", "source": 'token.a == "x"', "rev": 1})
    assert ok.status_code == 200
    r = await client.put(path, json={"name": "c", "source": 'token.a == "y"', "rev": 1})
    assert r.status_code == 409
    assert r.json()["error"] == "rev_conflict"
    assert r.json()["current_rev"] == 2
    assert (await client.get(path)).json()["source"] == 'token.a == "x"'


async def test_put_rename_to_existing_name_conflicts(client: httpx.AsyncClient) -> None:
    await create(client, "first")
    second = await create(client, "second")
    r = await client.put(
        f"{BASE}/{second['id']}", json={"name": "first", "source": RULE, "rev": 1}
    )
    assert r.status_code == 409
    assert r.json()["error"] == "policy_name_taken"


async def test_ac11_history_keeps_newest_twenty(client: httpx.AsyncClient) -> None:
    created = await create(client, "h")
    path = f"{BASE}/{created['id']}"
    for rev in range(1, 25):
        r = await client.put(path, json={"name": "h", "source": f'token.a == "v{rev}"', "rev": rev})
        assert r.status_code == 200
    r = await client.get(f"{path}/history")
    revs = [i["rev"] for i in r.json()["items"]]
    assert revs == list(range(25, 5, -1))


async def test_ac11_restore_writes_new_revision(client: httpx.AsyncClient) -> None:
    created = await create(client, "r")
    path = f"{BASE}/{created['id']}"
    await client.put(path, json={"name": "r", "source": 'token.a == "x"', "rev": 1})
    r = await client.post(f"{path}/restore", json={"rev": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["rev"] == 3
    assert body["source"] == created["source"]
    revs = [i["rev"] for i in (await client.get(f"{path}/history")).json()["items"]]
    assert revs == [3, 2, 1]


async def test_restore_unknown_rev_is_not_found(client: httpx.AsyncClient) -> None:
    created = await create(client, "r")
    r = await client.post(f"{BASE}/{created['id']}/restore", json={"rev": 99})
    assert r.status_code == 404
    assert r.json()["error"] == "not_found"


async def insert_resource(
    owner_exec: OwnerExec, tenant: uuid.UUID, policy_id: str, slug: str, visibility: str
) -> None:
    await owner_exec(
        "INSERT INTO registry (tenant_id, type, slug, name, visibility, policy_id, "
        "created_by, updated_by) VALUES (%s, 'agent', %s, %s, %s, %s, 'u1', 'u1')",
        (tenant, slug, slug, visibility, policy_id),
    )


async def test_usage_count_and_resources_reflect_referencing_rows(
    client: httpx.AsyncClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    created = await create(client, "used")
    other = await create(client, "unused", 'token.a == "x"')
    await insert_resource(owner_exec, tenant_id, created["id"], "res-one", "restricted")
    await insert_resource(owner_exec, tenant_id, created["id"], "res-two", "tenant")
    path = f"{BASE}/{created['id']}"
    assert (await client.get(path)).json()["usage_count"] == 2
    items = (await client.get(f"{path}/resources")).json()["items"]
    assert {i["slug"] for i in items} == {"res-one", "res-two"}
    assert (await client.get(f"{BASE}/{other['id']}/resources")).json()["items"] == []
    listed = {i["name"]: i["usage_count"] for i in (await client.get(BASE)).json()["items"]}
    assert listed == {"used": 2, "unused": 0}


async def test_ac12_delete_in_use_policy_conflicts(
    client: httpx.AsyncClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    created = await create(client, "busy")
    await insert_resource(owner_exec, tenant_id, created["id"], "res-one", "restricted")
    r = await client.delete(f"{BASE}/{created['id']}")
    assert r.status_code == 409
    assert r.json()["error"] == "policy_in_use"
    assert (await client.get(f"{BASE}/{created['id']}")).status_code == 200


async def test_delete_unused_policy_removes_it(client: httpx.AsyncClient) -> None:
    created = await create(client, "gone")
    r = await client.delete(f"{BASE}/{created['id']}")
    assert r.status_code == 204
    assert (await client.get(f"{BASE}/{created['id']}")).status_code == 404


async def test_ac12_reserved_policy_cannot_be_deleted_or_renamed(
    client: httpx.AsyncClient, owner_exec: OwnerExec
) -> None:
    created = await create(client, "locked")
    await owner_exec("UPDATE access_policies SET reserved = true WHERE id = %s", (created["id"],))
    path = f"{BASE}/{created['id']}"
    deleted = await client.delete(path)
    renamed = await client.put(path, json={"name": "other", "source": RULE, "rev": 1})
    assert deleted.status_code == renamed.status_code == 409
    assert deleted.json()["error"] == renamed.json()["error"] == "policy_reserved"
    kept = await client.put(path, json={"name": "locked", "source": 'token.a == "x"', "rev": 1})
    assert kept.status_code == 200


async def test_create_with_reserved_name_is_rejected(client: httpx.AsyncClient) -> None:
    r = await client.post(BASE, json={"name": "registry-admins", "source": RULE})
    assert r.status_code == 409
    assert r.json()["error"] == "policy_reserved"


async def test_max_policies_limit_is_enforced(
    client: httpx.AsyncClient, owner_exec: OwnerExec, tenant_id: uuid.UUID
) -> None:
    await owner_exec(
        "INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value) "
        "VALUES ('tenant', %s, NULL, 'max_policies', 1)",
        (str(tenant_id),),
    )
    await create(client, "only")
    r = await client.post(BASE, json={"name": "second", "source": RULE})
    assert r.status_code == 409
    body = r.json()
    assert body["error"] == "policy_limit_reached"
    assert body["max"] == 1


async def test_non_admin_gets_403_on_every_endpoint(
    make_client: MakeClient, tenant_id: uuid.UUID
) -> None:
    pid = uuid.uuid4()
    async with make_client(tenant_id, admin=False) as c:
        responses = [
            await c.post(BASE, json={"name": "x", "source": RULE}),
            await c.get(BASE),
            await c.get(f"{BASE}/{pid}"),
            await c.put(f"{BASE}/{pid}", json={"name": "x", "source": RULE, "rev": 1}),
            await c.delete(f"{BASE}/{pid}"),
            await c.get(f"{BASE}/{pid}/resources"),
            await c.get(f"{BASE}/{pid}/history"),
            await c.post(f"{BASE}/{pid}/restore", json={"rev": 1}),
            await c.post(f"{BASE}/{pid}/test", json={"token": {}}),
            await c.post(f"{BASE}/preview", json={"source": RULE}),
        ]
    assert [r.status_code for r in responses] == [403] * 10
    assert {r.json()["error"] for r in responses} == {"forbidden"}


async def test_other_tenants_policy_is_not_found(
    client: httpx.AsyncClient, make_client: MakeClient
) -> None:
    created = await create(client, "mine")
    path = f"{BASE}/{created['id']}"
    async with make_client(uuid.uuid4()) as other:
        responses = [
            await other.get(path),
            await other.put(path, json={"name": "mine", "source": RULE, "rev": 1}),
            await other.delete(path),
            await other.get(f"{path}/resources"),
            await other.get(f"{path}/history"),
            await other.post(f"{path}/restore", json={"rev": 1}),
            await other.post(f"{path}/test", json={"token": {}}),
        ]
        listed = await other.get(BASE)
    assert [r.status_code for r in responses] == [404] * 7
    assert listed.json()["items"] == []
    assert (await client.get(path)).status_code == 200


async def test_ac13_test_endpoint_reports_leaves_and_warnings(
    client: httpx.AsyncClient,
) -> None:
    rule = (
        'token.department == "billing" && ("manager" in token.roles '
        '|| "support-lead" in token.roles) && !("contractors" in token.groups) '
        "&& token.clearance >= 2"
    )
    created = await create(client, "t", rule)
    sample = {
        "department": "billing",
        "roles": ["manager"],
        "groups": ["contractors"],
        "clearance": "3",
        "_claim_names": {"groups": "src1"},
    }
    r = await client.post(
        f"{BASE}/{created['id']}/test", json={"token": sample, "principal": None}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["visible"] is False
    leaves = {leaf["text"]: leaf for leaf in body["leaves"]}
    assert leaves['token.department == "billing"'] == {
        "text": 'token.department == "billing"',
        "result": True,
    }
    assert leaves['"contractors" in token.groups']["result"] is True
    assert leaves['"contractors" in token.groups']["note"] == "negated in the rule"
    assert leaves['"support-lead" in token.roles']["result"] is False
    warnings = " | ".join(body["warnings"])
    assert "token.clearance is a string" in warnings
    assert "overage" in warnings


async def test_ac13_test_endpoint_reports_absent_claim_and_persists_nothing(
    client: httpx.AsyncClient,
) -> None:
    created = await create(client, "t")
    path = f"{BASE}/{created['id']}"
    r = await client.post(f"{path}/test", json={"token": {"department": "billing"}})
    body = r.json()
    assert any("token.roles is absent" in w for w in body["warnings"])
    visible = await client.post(
        f"{path}/test", json={"token": {"department": "billing", "roles": ["manager"]}}
    )
    assert visible.json()["visible"] is True
    after = (await client.get(path)).json()
    assert after["rev"] == 1
    assert len((await client.get(f"{path}/history")).json()["items"]) == 1


async def test_preview_returns_ast_path_warnings_and_summary(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{BASE}/preview", json={"source": RULE})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"ast", "compiled_path", "warnings", "summary", "source"}
    assert body["warnings"] == []
    assert (await client.get(BASE)).json()["items"] == []


async def test_preview_with_sample_returns_warnings(client: httpx.AsyncClient) -> None:
    r = await client.post(
        f"{BASE}/preview", json={"source": "token.clearance >= 2", "token": {"clearance": "3"}}
    )
    assert any("token.clearance is a string" in w for w in r.json()["warnings"])


async def test_preview_parse_error_is_422(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{BASE}/preview", json={"source": "token.a =="})
    assert r.status_code == 422
    assert r.json()["error"] == "policy_parse_error"
