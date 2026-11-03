from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
ALTER TABLE registry DROP CONSTRAINT registry_policy_id_tenant_id_fkey;
ALTER TABLE registry DROP COLUMN visibility, DROP COLUMN policy_id;
INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value)
VALUES ('global', NULL, NULL, 'max_policies_per_resource_action', 10);
""")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
DELETE FROM resource_limits WHERE limit_key = 'max_policies_per_resource_action';
ALTER TABLE registry
  ADD COLUMN visibility text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private','tenant','restricted')),
  ADD COLUMN policy_id uuid;
UPDATE registry r SET visibility = 'tenant'
FROM registry_policies rp JOIN access_policies p ON p.id = rp.policy_id AND p.kind = 'open'
WHERE rp.registry_id = r.id AND rp.action = 'read';
UPDATE registry r SET visibility = 'restricted', policy_id = s.policy_id
FROM (SELECT DISTINCT ON (rp.registry_id) rp.registry_id, rp.policy_id FROM registry_policies rp
      JOIN access_policies p ON p.id = rp.policy_id AND p.kind = 'rule'
      WHERE rp.action = 'read' ORDER BY rp.registry_id, rp.policy_id) s
WHERE s.registry_id = r.id;
ALTER TABLE registry ADD CONSTRAINT registry_check CHECK (visibility <> 'restricted' OR policy_id IS NOT NULL);
ALTER TABLE registry ADD CONSTRAINT registry_policy_id_tenant_id_fkey
  FOREIGN KEY (policy_id, tenant_id) REFERENCES access_policies(id, tenant_id) ON DELETE RESTRICT;
""")
