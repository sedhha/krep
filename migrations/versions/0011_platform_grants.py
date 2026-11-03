from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
GRANT SELECT, INSERT, UPDATE, DELETE ON access_policies, access_policy_history, memberships, auth_configs TO krep_platform;
GRANT INSERT ON admin_audit_log TO krep_app;
GRANT USAGE ON SEQUENCE admin_audit_log_id_seq TO krep_app;
GRANT SELECT ON resource_limits, auth_users, registry, registry_policies TO krep_platform;
""")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("""
REVOKE ALL ON admin_audit_log FROM krep_app;
REVOKE ALL ON SEQUENCE admin_audit_log_id_seq FROM krep_app;
REVOKE ALL ON access_policies, access_policy_history, memberships, auth_configs, resource_limits, auth_users, registry, registry_policies FROM krep_platform;
""")
