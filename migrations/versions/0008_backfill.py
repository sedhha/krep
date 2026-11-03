from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
ALTER TABLE registry_policies NO FORCE ROW LEVEL SECURITY;
ALTER TABLE access_policies NO FORCE ROW LEVEL SECURITY;
ALTER TABLE access_policy_history NO FORCE ROW LEVEL SECURITY;
ALTER TABLE registry NO FORCE ROW LEVEL SECURITY;
ALTER TABLE registry_versions NO FORCE ROW LEVEL SECURITY;
ALTER TABLE agents NO FORCE ROW LEVEL SECURITY;
ALTER TABLE skills NO FORCE ROW LEVEL SECURITY;
ALTER TABLE skill_files NO FORCE ROW LEVEL SECURITY;
ALTER TABLE registry_links NO FORCE ROW LEVEL SECURITY;
ALTER TABLE registry_version_deps NO FORCE ROW LEVEL SECURITY;
ALTER TABLE search_synonyms NO FORCE ROW LEVEL SECURITY;
INSERT INTO organizations (slug,name,is_platform,created_by) VALUES ('platform','Platform',true,'migration') ON CONFLICT (slug) DO NOTHING;
INSERT INTO organizations (id,slug,name,created_by) SELECT tenant_id, 'tenant-' || left(tenant_id::text,8), 'Migrated tenant', 'migration' FROM (SELECT tenant_id FROM access_policies UNION SELECT tenant_id FROM access_policy_history UNION SELECT tenant_id FROM registry UNION SELECT tenant_id FROM registry_versions UNION SELECT tenant_id FROM agents UNION SELECT tenant_id FROM skills UNION SELECT tenant_id FROM skill_files UNION SELECT tenant_id FROM registry_links UNION SELECT tenant_id FROM registry_version_deps UNION SELECT tenant_id FROM search_synonyms UNION SELECT tenant_id FROM api_keys UNION SELECT tenant_id FROM token_issuers WHERE tenant_id IS NOT NULL UNION SELECT scope_id::uuid FROM resource_limits WHERE scope_type = 'tenant') tenants ON CONFLICT (id) DO NOTHING;
INSERT INTO access_policies (tenant_id,name,ast,source,compiled_path,compiler_version,reserved,kind,created_by,updated_by)
SELECT o.id, p.name, '{}'::jsonb, 'true', 'true'::jsonpath, 1, true, 'open', 'migration', 'migration'
FROM organizations o CROSS JOIN (VALUES ('open-to-all'),('registry-readers')) p(name) WHERE NOT o.is_platform
ON CONFLICT (tenant_id,name) DO NOTHING;
INSERT INTO registry_policies (registry_id,tenant_id,action,policy_id)
SELECT r.id,r.tenant_id,'read',CASE WHEN r.visibility = 'restricted' THEN r.policy_id ELSE p.id END
FROM registry r JOIN access_policies p ON p.tenant_id = r.tenant_id AND p.name = 'open-to-all'
WHERE r.visibility IN ('tenant','restricted') ON CONFLICT DO NOTHING;

ALTER TABLE registry_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE access_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE access_policy_history FORCE ROW LEVEL SECURITY;
ALTER TABLE registry FORCE ROW LEVEL SECURITY;
ALTER TABLE registry_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE agents FORCE ROW LEVEL SECURITY;
ALTER TABLE skills FORCE ROW LEVEL SECURITY;
ALTER TABLE skill_files FORCE ROW LEVEL SECURITY;
ALTER TABLE registry_links FORCE ROW LEVEL SECURITY;
ALTER TABLE registry_version_deps FORCE ROW LEVEL SECURITY;
ALTER TABLE search_synonyms FORCE ROW LEVEL SECURITY;
""")


def downgrade() -> None:
    # Preserve backfilled identities and policies that may have acquired references.
    pass
