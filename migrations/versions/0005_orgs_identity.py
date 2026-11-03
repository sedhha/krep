from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
CREATE TABLE organizations (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
  name          text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','pending_delete')),
  is_platform   boolean NOT NULL DEFAULT false,
  delete_after  timestamptz,
  legal_hold    boolean NOT NULL DEFAULT false,
  created_by    text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'pending_delete') = (delete_after IS NOT NULL))
);
CREATE UNIQUE INDEX organizations_one_platform ON organizations (is_platform) WHERE is_platform;
CREATE FUNCTION platform_tenant_id() RETURNS uuid LANGUAGE sql STABLE
  AS $$ SELECT id FROM organizations WHERE is_platform $$;

CREATE TABLE products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES organizations(id),
  slug text NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, slug), UNIQUE (id, tenant_id)
);

CREATE TABLE auth_configs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES organizations(id),
  product_id uuid,
  adapter text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}',
  secret_enc bytea, key_id text,
  rev int NOT NULL DEFAULT 1,
  enabled boolean NOT NULL DEFAULT true,
  updated_by text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (product_id, tenant_id) REFERENCES products(id, tenant_id),
  UNIQUE NULLS NOT DISTINCT (tenant_id, product_id)
);

CREATE TABLE memberships (
  user_id    text NOT NULL,
  tenant_id  uuid NOT NULL REFERENCES organizations(id),
  groups     text[] NOT NULL DEFAULT '{}' CHECK (cardinality(groups) <= 20),
  created_by text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, tenant_id)
);

CREATE TABLE platform_admins (
  user_id text PRIMARY KEY, granted_by text NOT NULL, granted_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE disabled_users (
  user_id text PRIMARY KEY, reason text NOT NULL DEFAULT '', disabled_by text NOT NULL, disabled_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE admin_audit_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  actor text NOT NULL, action text NOT NULL, tenant_id uuid, target text,
  detail jsonb,
  at timestamptz NOT NULL DEFAULT now()
);

""")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
DROP TABLE admin_audit_log, disabled_users, platform_admins, memberships, auth_configs, products;
DROP FUNCTION platform_tenant_id();
DROP TABLE organizations;
""")
