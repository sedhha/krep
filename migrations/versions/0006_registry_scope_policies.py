from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
CREATE TABLE registry_policies (
  registry_id uuid NOT NULL,
  tenant_id   uuid NOT NULL,
  action      text NOT NULL CHECK (action IN ('read','manage')),
  policy_id   uuid NOT NULL,
  PRIMARY KEY (registry_id, action, policy_id),
  FOREIGN KEY (registry_id, tenant_id) REFERENCES registry(id, tenant_id) ON DELETE CASCADE,
  FOREIGN KEY (policy_id, tenant_id) REFERENCES access_policies(id, tenant_id) ON DELETE RESTRICT
);
CREATE INDEX registry_policies_policy ON registry_policies (policy_id);

CREATE TABLE link_scope_rules (
  source_scope text NOT NULL CHECK (source_scope IN ('org','product','global')),
  target_scope text NOT NULL CHECK (target_scope IN ('org','product','global')),
  allowed boolean NOT NULL,
  PRIMARY KEY (source_scope, target_scope),
  CHECK (source_scope <> 'global' OR target_scope = 'global' OR NOT allowed)
);

ALTER TABLE access_policies ADD COLUMN kind text NOT NULL DEFAULT 'rule' CHECK (kind IN ('rule','open'));
ALTER TABLE registry
  ADD COLUMN scope text NOT NULL DEFAULT 'org' CHECK (scope IN ('org','product','global')),
  ADD COLUMN product_id uuid,
  ADD FOREIGN KEY (product_id, tenant_id) REFERENCES products(id, tenant_id),
  ADD CHECK ((scope = 'product') = (product_id IS NOT NULL));

ALTER TABLE registry DROP CONSTRAINT registry_tenant_id_type_slug_key;
ALTER TABLE registry ADD CONSTRAINT registry_scope_slug_key UNIQUE NULLS NOT DISTINCT (tenant_id, product_id, type, slug);
INSERT INTO link_scope_rules VALUES
('org','org',true),('org','product',true),('product','org',true),('product','product',true),
('global','global',true),('org','global',true),('product','global',true),('global','org',false),('global','product',false);
CREATE FUNCTION enforce_global_scope() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.scope = 'global' AND (TG_OP = 'INSERT' OR OLD.scope IS DISTINCT FROM NEW.scope)
     AND current_setting('app.platform_admin', true) IS DISTINCT FROM 'on' THEN
    RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'global scope requires platform admin';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER registry_global_scope BEFORE INSERT OR UPDATE OF scope ON registry
FOR EACH ROW EXECUTE FUNCTION enforce_global_scope();

""")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
DROP TRIGGER registry_global_scope ON registry;
DROP FUNCTION enforce_global_scope();
DROP TABLE registry_policies, link_scope_rules;
ALTER TABLE registry DROP CONSTRAINT registry_scope_slug_key;
ALTER TABLE registry DROP COLUMN product_id, DROP COLUMN scope;
ALTER TABLE registry ADD CONSTRAINT registry_tenant_id_type_slug_key UNIQUE (tenant_id, type, slug);
ALTER TABLE access_policies DROP COLUMN kind;
""")
