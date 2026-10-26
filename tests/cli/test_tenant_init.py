from collections.abc import Callable
from typing import Any

import pytest

from krep.cli import main
from tests.cli.conftest import ADMIN_RULE, WRITER_RULE

ADMIN_PATH = 'exists($."token"."groups"[*] ? (@ == "grc-admins"))'
POLICIES = (
    "SELECT name, reserved, rev, source, compiled_path::text, created_by "
    "FROM access_policies WHERE tenant_id = %s ORDER BY name"
)


def init(tenant: str, admin: str = ADMIN_RULE, writer: str = WRITER_RULE) -> int:
    return main(
        ["tenant", "init", "--tenant", tenant, "--admin-rule", admin, "--writer-rule", writer]
    )


def test_ac4_tenant_init_creates_both_reserved_policies(
    tenant: str, query: Callable[..., list[tuple[Any, ...]]]
) -> None:
    assert init(tenant) == 0
    rows = query(POLICIES, tenant)
    assert [r[:4] for r in rows] == [
        ("registry-admins", True, 1, ADMIN_RULE),
        ("registry-writers", True, 1, WRITER_RULE),
    ]
    assert rows[0][4] == query("SELECT %s::jsonpath::text", ADMIN_PATH)[0][0]
    assert all(r[5] for r in rows)


def test_ac4_tenant_init_is_idempotent(
    tenant: str, query: Callable[..., list[tuple[Any, ...]]]
) -> None:
    assert init(tenant) == 0
    assert init(tenant, admin='token.groups == "someone-else"') == 0
    rows = query(POLICIES, tenant)
    assert [(r[0], r[2], r[3]) for r in rows] == [
        ("registry-admins", 1, ADMIN_RULE),
        ("registry-writers", 1, WRITER_RULE),
    ]


def test_tenant_init_invalid_rule_writes_nothing(
    tenant: str, query: Callable[..., list[tuple[Any, ...]]], capsys: Any
) -> None:
    assert init(tenant, writer="token.a ==") != 0
    assert "policy_parse_error" in capsys.readouterr().err
    assert query(POLICIES, tenant) == []


def test_tenant_init_rejects_non_uuid_tenant(capsys: Any) -> None:
    with pytest.raises(SystemExit) as exc:
        init("not-a-uuid")
    assert exc.value.code != 0
    assert "tenant" in capsys.readouterr().err


def test_tenant_init_isolates_tenants(
    tenant: str, query: Callable[..., list[tuple[Any, ...]]]
) -> None:
    other = "00000000-0000-4000-8000-0000000000b2"
    assert init(tenant) == 0
    assert init(other, admin='token.groups == "other-admins"') == 0
    assert query("SELECT source FROM access_policies WHERE tenant_id = %s AND name = 'registry-admins'", other) == [
        ('token.groups == "other-admins"',)
    ]

