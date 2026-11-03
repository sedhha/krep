from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
CREATE FUNCTION purge_organization(p_org uuid) RETURNS void
LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
  org record;
BEGIN
  SELECT * INTO org FROM organizations WHERE id = p_org FOR UPDATE;
  IF NOT FOUND THEN
    RETURN;
  END IF;
  IF org.is_platform OR org.status <> 'pending_delete' OR org.legal_hold OR org.delete_after > now() THEN
    RAISE EXCEPTION 'organization %% is not purgeable', p_org USING ERRCODE = '55000';
  END IF;
  PERFORM set_config('app.tenant_id', p_org::text, true);
  DELETE FROM resource_limits WHERE (scope_type IN ('tenant', 'org') AND scope_id = p_org::text)
    OR (scope_type = 'product' AND scope_id IN (SELECT id::text FROM products WHERE tenant_id = p_org));
  DELETE FROM registry_version_deps WHERE tenant_id = p_org;
  DELETE FROM registry_links WHERE tenant_id = p_org;
  DELETE FROM registry WHERE tenant_id = p_org;
  DELETE FROM skill_files WHERE tenant_id = p_org;
  DELETE FROM access_policies WHERE tenant_id = p_org;
  DELETE FROM search_synonyms WHERE tenant_id = p_org;
  DELETE FROM auth_configs WHERE tenant_id = p_org;
  DELETE FROM products WHERE tenant_id = p_org;
  DELETE FROM memberships WHERE tenant_id = p_org;
  DELETE FROM api_keys WHERE tenant_id = p_org;
  DELETE FROM token_issuers WHERE tenant_id = p_org;
  UPDATE admin_audit_log SET detail = NULL WHERE tenant_id = p_org;
  DELETE FROM organizations WHERE id = p_org;
END $$;
REVOKE ALL ON FUNCTION purge_organization(uuid) FROM PUBLIC;
""")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP FUNCTION purge_organization(uuid)")
