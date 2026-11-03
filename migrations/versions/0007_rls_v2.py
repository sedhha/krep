from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE products FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON products USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON products TO krep_app;
ALTER TABLE auth_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_configs FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON auth_configs USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON auth_configs TO krep_app;
ALTER TABLE registry_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE registry_policies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON registry_policies USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON registry_policies TO krep_app;
ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON memberships USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON memberships TO krep_app;
CREATE POLICY own_memberships ON memberships FOR SELECT USING (user_id = NULLIF(current_setting('app.user_id', true), ''));
GRANT SELECT ON organizations, platform_admins, disabled_users, link_scope_rules TO krep_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON organizations, platform_admins, disabled_users, admin_audit_log TO krep_platform;
GRANT USAGE ON SEQUENCE admin_audit_log_id_seq TO krep_platform;
CREATE POLICY global_read ON registry FOR SELECT USING (scope = 'global');
CREATE POLICY global_read ON registry_versions FOR SELECT USING (EXISTS (SELECT 1 FROM registry r WHERE r.id = registry_versions.registry_id AND r.tenant_id = registry_versions.tenant_id AND r.scope = 'global'));
CREATE POLICY global_read ON agents FOR SELECT USING (EXISTS (SELECT 1 FROM registry r WHERE r.id = agents.registry_id AND r.tenant_id = agents.tenant_id AND r.scope = 'global'));
CREATE POLICY global_read ON skills FOR SELECT USING (EXISTS (SELECT 1 FROM registry r WHERE r.id = skills.registry_id AND r.tenant_id = skills.tenant_id AND r.scope = 'global'));
CREATE POLICY global_read ON skill_files FOR SELECT USING (EXISTS (SELECT 1 FROM skills s JOIN registry r ON r.id = s.registry_id AND r.tenant_id = s.tenant_id WHERE s.tenant_id = skill_files.tenant_id AND s.content_sha256 = skill_files.content_sha256 AND r.scope = 'global'));
CREATE POLICY global_read ON registry_policies FOR SELECT USING (EXISTS (SELECT 1 FROM registry r WHERE r.id = registry_policies.registry_id AND r.tenant_id = registry_policies.tenant_id AND r.scope = 'global'));
CREATE POLICY global_read ON access_policies FOR SELECT USING (EXISTS (SELECT 1 FROM registry_policies rp JOIN registry r ON r.id = rp.registry_id AND r.tenant_id = rp.tenant_id WHERE rp.policy_id = access_policies.id AND rp.tenant_id = access_policies.tenant_id AND r.scope = 'global'));
""")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
DROP POLICY own_memberships ON memberships;
DROP POLICY global_read ON access_policies;
DROP POLICY global_read ON registry_policies;
DROP POLICY global_read ON skill_files;
DROP POLICY global_read ON skills;
DROP POLICY global_read ON agents;
DROP POLICY global_read ON registry_versions;
DROP POLICY global_read ON registry;
REVOKE ALL ON products FROM krep_app;
DROP POLICY tenant_isolation ON products;
ALTER TABLE products NO FORCE ROW LEVEL SECURITY;
ALTER TABLE products DISABLE ROW LEVEL SECURITY;
REVOKE ALL ON auth_configs FROM krep_app;
DROP POLICY tenant_isolation ON auth_configs;
ALTER TABLE auth_configs NO FORCE ROW LEVEL SECURITY;
ALTER TABLE auth_configs DISABLE ROW LEVEL SECURITY;
REVOKE ALL ON registry_policies FROM krep_app;
DROP POLICY tenant_isolation ON registry_policies;
ALTER TABLE registry_policies NO FORCE ROW LEVEL SECURITY;
ALTER TABLE registry_policies DISABLE ROW LEVEL SECURITY;
REVOKE ALL ON memberships FROM krep_app;
DROP POLICY tenant_isolation ON memberships;
ALTER TABLE memberships NO FORCE ROW LEVEL SECURITY;
ALTER TABLE memberships DISABLE ROW LEVEL SECURITY;
REVOKE ALL ON organizations, platform_admins, disabled_users, link_scope_rules FROM krep_app;
REVOKE ALL ON organizations, platform_admins, disabled_users, admin_audit_log FROM krep_platform;
REVOKE ALL ON SEQUENCE admin_audit_log_id_seq FROM krep_platform;
""")
