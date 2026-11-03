import uuid

import psycopg

from tests.conftest import alembic, role_url


def test_v2ac17_migrates_v1_visibility_and_all_tenant_sources(scratch_db: str):
    alembic(scratch_db, "upgrade", "0004")
    tenant, keys_tenant, issuer_tenant, limits_tenant = [uuid.uuid4() for _ in range(4)]
    with psycopg.connect(role_url("krep_owner", scratch_db)) as conn:
        conn.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
        policy = conn.execute(
            "INSERT INTO access_policies (tenant_id,name,ast,source,compiled_path,compiler_version,created_by,updated_by) VALUES (%s,'existing','{}','true','true',1,'u','u') RETURNING id",
            (tenant,),
        ).fetchone()[0]
        for visibility in ("private", "tenant", "restricted"):
            conn.execute(
                "INSERT INTO registry (tenant_id,type,slug,name,visibility,policy_id,created_by,updated_by) VALUES (%s,'agent',%s,'A',%s,%s,'u','u')",
                (
                    tenant,
                    visibility,
                    visibility,
                    policy if visibility == "restricted" else None,
                ),
            )
        conn.execute(
            "INSERT INTO api_keys (tenant_id,name,key_hash) VALUES (%s,'key','hash')",
            (keys_tenant,),
        )
        conn.execute(
            "INSERT INTO token_issuers (issuer,audience,jwks_uri,tenant_id) VALUES ('issuer','aud','https://example.com',%s)",
            (issuer_tenant,),
        )
        conn.execute(
            "INSERT INTO resource_limits (scope_type,scope_id,limit_key,value) VALUES ('tenant',%s,'max_drafts',1)",
            (str(limits_tenant),),
        )
    alembic(scratch_db, "upgrade", "head")
    with psycopg.connect(role_url("krep_app", scratch_db)) as conn:
        assert set(
            conn.execute(
                "SELECT id FROM organizations WHERE NOT is_platform"
            ).fetchall()
        ) == {(t,) for t in (tenant, keys_tenant, issuer_tenant, limits_tenant)}
        for t in (tenant, keys_tenant, issuer_tenant, limits_tenant):
            conn.execute("SELECT set_config('app.tenant_id',%s,true)", (str(t),))
            assert conn.execute(
                "SELECT slug FROM organizations WHERE id = %s", (t,)
            ).fetchone() == (f"tenant-{str(t)[:8]}",)
            assert set(
                conn.execute(
                    "SELECT name,kind,compiled_path::text FROM access_policies WHERE name IN ('open-to-all','registry-readers')"
                ).fetchall()
            ) == {("open-to-all", "open", "true"), ("registry-readers", "open", "true")}
        conn.execute("SELECT set_config('app.tenant_id',%s,true)", (str(tenant),))
        assert conn.execute(
            "SELECT r.slug,p.name FROM registry r LEFT JOIN registry_policies rp ON rp.registry_id=r.id LEFT JOIN access_policies p ON p.id=rp.policy_id ORDER BY r.slug"
        ).fetchall() == [
            ("private", None),
            ("restricted", "existing"),
            ("tenant", "open-to-all"),
        ]
        assert conn.execute("SELECT DISTINCT scope FROM registry").fetchall() == [
            ("org",)
        ]
    alembic(scratch_db, "downgrade", "0007")
    alembic(scratch_db, "upgrade", "head")
    alembic(scratch_db, "downgrade", "0004")
    alembic(scratch_db, "upgrade", "head")
