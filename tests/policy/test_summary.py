from krep.policy.parser import parse
from krep.policy.summary import summarize


def summary_of(rule: str) -> str:
    return summarize(parse(rule))


def test_ac13_worked_example_summary() -> None:
    rule = (
        'token.department == "billing" '
        '&& ("manager" in token.roles || "support-lead" in token.roles) '
        '&& !("contractors" in token.groups)'
    )
    assert summary_of(rule) == (
        'Visible when: department is "billing", AND '
        '(roles contains "manager" OR roles contains "support-lead"), AND '
        'NOT groups contains "contractors".'
    )


def test_single_leaf() -> None:
    assert summary_of('token.department == "billing"') == (
        'Visible when: department is "billing".'
    )


def test_comparisons() -> None:
    assert summary_of("token.clearance >= 3") == "Visible when: clearance is at least 3."
    assert summary_of("token.clearance > 3") == (
        "Visible when: clearance is greater than 3."
    )
    assert summary_of("token.clearance < 3") == "Visible when: clearance is less than 3."
    assert summary_of("token.clearance <= 3") == "Visible when: clearance is at most 3."
    assert summary_of('token.roles != "admin"') == (
        'Visible when: roles is not "admin".'
    )


def test_list_string_presence_and_nested_paths() -> None:
    assert summary_of('token.org.region in ["emea","apac"]') == (
        'Visible when: org.region is one of "emea", "apac".'
    )
    assert summary_of('token.email.startsWith("a@")') == (
        'Visible when: email starts with "a@".'
    )
    assert summary_of('token.email.endsWith("@acme.com")') == (
        'Visible when: email ends with "@acme.com".'
    )
    assert summary_of("has(token.org.region)") == (
        "Visible when: org.region is present."
    )


def test_principal_paths_keep_their_root() -> None:
    assert summary_of('"support" in principal.roles') == (
        'Visible when: principal.roles contains "support".'
    )


def test_tenant_variable_and_null() -> None:
    assert summary_of("token.tid == var.tenant_id") == (
        "Visible when: tid is the tenant id."
    )
    assert summary_of("token.nul == null") == "Visible when: nul is null."


def test_not_over_group_is_parenthesised() -> None:
    assert summary_of('!(token.a == "x" || token.b == "y")') == (
        'Visible when: NOT (a is "x" OR b is "y").'
    )
