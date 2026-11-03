from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql("""
CREATE FUNCTION foreign_referrers(p_resource uuid, p_version uuid DEFAULT NULL)
RETURNS TABLE (organization text, kind text, referrers bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
  previous text := coalesce(current_setting('app.tenant_id', true), '');
  platform boolean := current_setting('app.platform_admin', true) = 'on';
  org record;
  n bigint;
BEGIN
  FOR org IN SELECT o.id, o.slug FROM organizations o WHERE o.id::text <> previous ORDER BY o.slug LOOP
    PERFORM set_config('app.tenant_id', org.id::text, true);
    SELECT count(*) INTO n FROM registry_links l
    WHERE (p_version IS NULL AND l.target_id = p_resource)
       OR l.pinned_version_id IN (SELECT v.id FROM registry_versions v WHERE v.id = p_version OR (p_version IS NULL AND v.registry_id = p_resource));
    IF n > 0 THEN
      organization := CASE WHEN platform THEN org.slug END; kind := 'link'; referrers := n;
      RETURN NEXT;
    END IF;
    SELECT count(*) INTO n FROM registry_version_deps d
    WHERE d.depends_on_version_id IN (SELECT v.id FROM registry_versions v WHERE v.id = p_version OR (p_version IS NULL AND v.registry_id = p_resource));
    IF n > 0 THEN
      organization := CASE WHEN platform THEN org.slug END; kind := 'version_dep'; referrers := n;
      RETURN NEXT;
    END IF;
  END LOOP;
  PERFORM set_config('app.tenant_id', previous, true);
END $$;
REVOKE ALL ON FUNCTION foreign_referrers(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION foreign_referrers(uuid, uuid) TO krep_app;
""")


def downgrade() -> None:
    op.get_bind().exec_driver_sql("DROP FUNCTION foreign_referrers(uuid, uuid)")
