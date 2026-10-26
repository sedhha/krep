from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = op.get_bind().exec_driver_sql
    sql(
        "CREATE TABLE tenants ("
        "tenant_id uuid PRIMARY KEY, "
        "created_at timestamptz NOT NULL DEFAULT now())"
    )


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP TABLE tenants")
