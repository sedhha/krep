from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = op.get_bind().exec_driver_sql
    sql(
        "INSERT INTO registry_types (type, subtype_table, description) VALUES "
        "('agent', 'agents', 'LangGraph-based agent'), "
        "('skill', 'skills', 'Instructions plus resources an agent can load')"
    )
    sql(
        "INSERT INTO link_rules (source_type, target_type, relation, auto_load_allowed, accept_by) "
        "VALUES ('agent', 'skill', 'uses', true, 'source')"
    )
    sql(
        "INSERT INTO resource_limits (scope_type, scope_id, resource_type, limit_key, value) VALUES "
        "('global', NULL, NULL, 'max_drafts', 50), "
        "('global', NULL, NULL, 'max_published_versions', 10), "
        "('global', NULL, NULL, 'max_policies', 500), "
        "('global', NULL, NULL, 'max_policy_nodes', 100), "
        "('global', NULL, NULL, 'max_synonym_groups', 200), "
        "('global', NULL, NULL, 'max_policy_history', 20)"
    )


def downgrade() -> None:
    sql = op.get_bind().exec_driver_sql
    sql("DELETE FROM resource_limits WHERE scope_type = 'global' AND resource_type IS NULL")
    sql("DELETE FROM link_rules WHERE source_type = 'agent' AND target_type = 'skill'")
    sql("DELETE FROM registry_types WHERE type IN ('agent', 'skill')")
