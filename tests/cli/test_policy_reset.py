from collections.abc import Callable
from typing import Any

import pytest

from krep.cli import main
from tests.cli.conftest import ADMIN_RULE, WRITER_RULE
from tests.cli.test_tenant_init import init

NEW_RULE = 'token.groups == "new-admins"'


def reset(name: str, tenant: str, rule: str) -> int:
    return main(["policy", "reset", name, "--tenant", tenant, "--rule", rule])


def state(query: Callable[..., list[tuple[Any, ...]]], tenant: str, name: str) -> tuple[Any, ...]:
    return query(
        "SELECT rev, source, compiled_path::text, reserved FROM access_policies "
        "WHERE tenant_id = %s AND name = %s",
        tenant,
        name,
    )[0]


def test_ac4_reset_replaces_rule_and_bumps_rev(
    tenant: str, query: Callable[..., list[tuple[Any, ...]]]
) -> None:
    init(tenant)
    assert reset("registry-admins", tenant, NEW_RULE) == 0
    rev, source, path, reserved = state(query, tenant, "registry-admins")
    assert (rev, source, reserved) == (2, NEW_RULE, True)
    assert "new-admins" in path
    assert state(query, tenant, "registry-writers")[:2] == (1, WRITER_RULE)
    assert query(
        "SELECT h.rev, h.source FROM access_policy_history h JOIN access_policies p "
        "ON p.id = h.policy_id WHERE p.tenant_id = %s AND p.name = 'registry-admins' "
        "ORDER BY h.rev",
        tenant,
    ) == [(1, ADMIN_RULE), (2, NEW_RULE)]


def test_ac4_reset_recovers_a_missing_reserved_policy(
    tenant: str, query: Callable[..., list[tuple[Any, ...]]]
) -> None:
    assert reset("registry-admins", tenant, NEW_RULE) == 0
    assert state(query, tenant, "registry-admins")[:2] == (1, NEW_RULE)


def test_reset_invalid_rule_exits_nonzero_and_writes_nothing(
    tenant: str, query: Callable[..., list[tuple[Any, ...]]], capsys: Any
) -> None:
    init(tenant)
    assert reset("registry-admins", tenant, "token.a ==") != 0
    assert "policy_parse_error" in capsys.readouterr().err
    assert state(query, tenant, "registry-admins")[:2] == (1, ADMIN_RULE)


def test_reset_only_accepts_reserved_names(
    tenant: str, query: Callable[..., list[tuple[Any, ...]]], capsys: Any
) -> None:
    init(tenant)
    with pytest.raises(SystemExit) as exc:
        reset("my-policy", tenant, NEW_RULE)
    assert exc.value.code != 0
    assert "registry-admins" in capsys.readouterr().err
    assert query("SELECT count(*) FROM access_policies WHERE tenant_id = %s", tenant) == [(2,)]


def test_reset_trims_history_to_max_policy_history(
    tenant: str, query: Callable[..., list[tuple[Any, ...]]]
) -> None:
    init(tenant)
    for i in range(24):
        assert reset("registry-admins", tenant, f'token.groups == "g{i}"') == 0
    assert state(query, tenant, "registry-admins")[0] == 25
    revs = [r[0] for r in query(
        "SELECT h.rev FROM access_policy_history h JOIN access_policies p ON p.id = h.policy_id "
        "WHERE p.tenant_id = %s AND p.name = 'registry-admins' ORDER BY h.rev",
        tenant,
    )]
    assert revs == list(range(6, 26))
