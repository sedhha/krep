from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

IMMUTABLE_TABLES = ["registry_versions", "agents", "skills"]


def upgrade() -> None:
    sql = op.get_bind().exec_driver_sql
    sql(
        "CREATE FUNCTION reject_published_update() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "IF TG_TABLE_NAME = 'registry_versions' THEN "
        "IF OLD.status = 'published' THEN "
        "RAISE EXCEPTION USING ERRCODE = '23514', "
        "MESSAGE = 'published version ' || OLD.id || ' is immutable'; "
        "END IF; "
        "ELSIF (SELECT status FROM registry_versions WHERE id = OLD.version_id) = 'published' THEN "
        "RAISE EXCEPTION USING ERRCODE = '23514', "
        "MESSAGE = 'published version ' || OLD.version_id || ' is immutable'; "
        "END IF; "
        "RETURN NEW; "
        "END $$"
    )
    for table in IMMUTABLE_TABLES:
        sql(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_published_update()"
        )
    sql(
        "CREATE FUNCTION reject_skill_file_update() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "RAISE EXCEPTION USING ERRCODE = '23514', "
        "MESSAGE = 'skill_files rows are content-addressed and never updated'; "
        "END $$"
    )
    sql(
        "CREATE TRIGGER skill_files_immutable BEFORE UPDATE ON skill_files "
        "FOR EACH ROW EXECUTE FUNCTION reject_skill_file_update()"
    )


def downgrade() -> None:
    sql = op.get_bind().exec_driver_sql
    sql("DROP TRIGGER skill_files_immutable ON skill_files")
    sql("DROP FUNCTION reject_skill_file_update()")
    for table in reversed(IMMUTABLE_TABLES):
        sql(f"DROP TRIGGER {table}_immutable ON {table}")
    sql("DROP FUNCTION reject_published_update()")
