from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
CREATE VIEW auth_users AS SELECT id, username, email, name FROM auth."user";
GRANT SELECT ON auth_users TO krep_app;
""")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
DROP VIEW auth_users;
""")
