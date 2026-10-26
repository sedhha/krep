from collections.abc import Callable
from typing import Any

import psycopg

from krep.cli import main
from krep.policy.compile import COMPILER_VERSION
from tests.cli.test_tenant_init import init
from tests.conftest import role_url

TENANTS = ("00000000-0000-4000-8000-0000000000c1", "00000000-0000-4000-8000-0000000000c2")
ADMIN_PATH = 'exists($."token"."groups"[*] ? (@ == "grc-admins"))'
STALE_PATH = '$."stale"'


def test_recompile_rewrites_paths_with_older_compiler_version(
    query: Callable[..., list[tuple[Any, ...]]],
    cli_db: str,
) -> None:
    for tenant in TENANTS:
        init(tenant)
    with psycopg.connect(role_url("postgres", cli_db), autocommit=True) as conn:
        conn.execute(
            "UPDATE access_policies SET compiled_path = %s::jsonpath, compiler_version = %s "
            "WHERE tenant_id = %s AND name = 'registry-admins'",
            (STALE_PATH, COMPILER_VERSION - 1, TENANTS[0]),
        )
        conn.execute(
            "UPDATE access_policies SET compiled_path = %s::jsonpath WHERE tenant_id = %s "
            "AND name = 'registry-admins'",
            (STALE_PATH, TENANTS[1]),
        )

    assert main(["policy", "recompile"]) == 0

    rows = dict(
        ((t, n), (p, v))
        for t, n, p, v in query(
            "SELECT tenant_id::text, name, compiled_path::text, compiler_version "
            "FROM access_policies WHERE tenant_id = ANY(%s::uuid[])",
            list(TENANTS),
        )
    )
    fixed = rows[(TENANTS[0], "registry-admins")]
    assert fixed[0] == query("SELECT %s::jsonpath::text", ADMIN_PATH)[0][0]
    assert fixed[1] == COMPILER_VERSION
    assert rows[(TENANTS[1], "registry-admins")][0] == STALE_PATH


def test_recompile_leaves_current_rows_and_revs_untouched(
    query: Callable[..., list[tuple[Any, ...]]],
) -> None:
    tenant = "00000000-0000-4000-8000-0000000000c3"
    init(tenant)
    assert main(["policy", "recompile"]) == 0
    assert query(
        "SELECT rev, compiler_version FROM access_policies WHERE tenant_id = %s", tenant
    ) == [(1, COMPILER_VERSION), (1, COMPILER_VERSION)]
