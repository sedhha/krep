from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

TENANT_TABLES = [
    "access_policies", "access_policy_history", "registry", "registry_versions",
    "agents", "skills", "skill_files", "registry_links", "registry_version_deps",
    "search_synonyms",
]
READ_ONLY_TABLES = "resource_limits, registry_types, link_rules, token_issuers, api_keys"


def upgrade() -> None:
    sql = op.get_bind().exec_driver_sql
    for t in TENANT_TABLES:
        sql(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        sql(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        sql(
            f"CREATE POLICY tenant_isolation ON {t} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO krep_app")
    sql("ALTER TABLE resource_limits ENABLE ROW LEVEL SECURITY")
    sql(
        "CREATE POLICY limits_read ON resource_limits FOR SELECT USING ("
        "scope_type = 'global' OR "
        "(scope_type = 'tenant' AND scope_id = current_setting('app.tenant_id', true)))"
    )
    sql(f"GRANT SELECT ON {READ_ONLY_TABLES} TO krep_app")


def downgrade() -> None:
    sql = op.get_bind().exec_driver_sql
    sql(f"REVOKE SELECT ON {READ_ONLY_TABLES} FROM krep_app")
    sql("DROP POLICY limits_read ON resource_limits")
    sql("ALTER TABLE resource_limits DISABLE ROW LEVEL SECURITY")
    for t in reversed(TENANT_TABLES):
        sql(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {t} FROM krep_app")
        sql(f"DROP POLICY tenant_isolation ON {t}")
        sql(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        sql(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
