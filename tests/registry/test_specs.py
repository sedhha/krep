import copy
import hashlib
import json
from typing import Any

import pytest

from krep.registry.specs import (
    VALIDATORS,
    canonical_json,
    content_hash,
    validate_resource_fields,
    validate_spec,
)

VALID_AGENT: dict[str, Any] = {
    "model": "claude-sonnet-5-5",
    "model_config": {"temperature": 0.2, "max_tokens": 4096},
    "system_prompt": "You are a refund assistant...",
    "input_schema": {
        "type": "object",
        "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"],
    },
    "output_schema": {"type": "object", "properties": {"decision": {"type": "string"}}},
    "hitl_rules": [
        {
            "when": "tool.name == 'refund' && request.arguments.amount > 500",
            "action": "require_approval",
        }
    ],
    "runtime_config": {"durable_background": True, "timeout_seconds": 900},
    "tool_refs": [],
}

VALID_FIELDS: dict[str, Any] = {
    "name": "Refund Assistant",
    "slug": "refund-assistant",
    "description": "Handles refund requests.",
    "tags": ["billing", "refunds"],
    "visibility": "tenant",
    "policy_id": None,
    "meta": {"owner_team": "billing-eng"},
}


def agent_errors(**changes: Any) -> dict[str, str]:
    spec = copy.deepcopy(VALID_AGENT)
    for key, value in changes.items():
        if value is ...:
            spec.pop(key, None)
        else:
            spec[key] = value
    return {e.field: e.message for e in validate_spec("agent", spec)}


def field_errors(**changes: Any) -> dict[str, str]:
    return {e.field: e.message for e in validate_resource_fields(**{**VALID_FIELDS, **changes})}


def test_validators_hold_agent_only() -> None:
    assert set(VALIDATORS) == {"agent"}


def test_agent_spec_from_spec_6_is_valid() -> None:
    assert validate_spec("agent", VALID_AGENT) == []


def test_agent_minimal_spec_is_valid() -> None:
    assert validate_spec("agent", {"model": "m", "system_prompt": "p"}) == []


def test_agent_missing_model_and_system_prompt() -> None:
    errors = agent_errors(model=..., system_prompt=...)
    assert set(errors) == {"spec.model", "spec.system_prompt"}


@pytest.mark.parametrize("key", ["model", "system_prompt"])
def test_agent_blank_required_strings_fail(key: str) -> None:
    assert f"spec.{key}" in agent_errors(**{key: "  "})


@pytest.mark.parametrize("key", ["input_schema", "output_schema"])
def test_agent_invalid_json_schema_fails_with_path(key: str) -> None:
    assert f"spec.{key}" in agent_errors(**{key: {"type": "not-a-type"}})


@pytest.mark.parametrize("key", ["input_schema", "output_schema"])
def test_agent_schema_must_be_object(key: str) -> None:
    assert f"spec.{key}" in agent_errors(**{key: "string"})


def test_agent_schema_is_checked_against_draft_2020_12() -> None:
    errors = agent_errors(input_schema={"prefixItems": "nope"})
    assert "spec.input_schema" in errors


def test_agent_unparsable_cel_fails_with_indexed_path() -> None:
    rules = [
        {"when": "a == 1", "action": "require_approval"},
        {"when": "a ==== 1", "action": "require_approval"},
    ]
    assert set(agent_errors(hitl_rules=rules)) == {"spec.hitl_rules[1].when"}


def test_agent_hitl_rule_shape() -> None:
    errors = agent_errors(hitl_rules=[{"action": "x"}, "nope", {"when": "a", "action": ""}])
    assert set(errors) == {
        "spec.hitl_rules[0].when",
        "spec.hitl_rules[1]",
        "spec.hitl_rules[2].action",
    }


def test_agent_tool_refs_are_not_validated() -> None:
    assert agent_errors(tool_refs=["anything", {"x": 1}, 7]) == {}


def test_agent_spec_must_be_object() -> None:
    errors = validate_spec("agent", ["x"])  # type: ignore[arg-type]
    assert [e.field for e in errors] == ["spec"]


def test_unknown_type_has_no_spec_validator() -> None:
    with pytest.raises(KeyError):
        validate_spec("skill", {})


def test_valid_resource_fields() -> None:
    assert validate_resource_fields(**VALID_FIELDS) == []


@pytest.mark.parametrize(
    ("slug", "ok"),
    [
        ("refund-assistant", True),
        ("ab", True),
        ("a" * 63, True),
        ("a", False),
        ("a" * 64, False),
        ("-ab", False),
        ("Ab", False),
        ("a_b", False),
        ("", False),
    ],
)
def test_slug_rule(slug: str, ok: bool) -> None:
    assert ("slug" not in field_errors(slug=slug)) is ok


@pytest.mark.parametrize(
    ("name", "ok"), [("x", True), ("x" * 120, True), ("", False), ("x" * 121, False)]
)
def test_name_rule(name: str, ok: bool) -> None:
    assert ("name" not in field_errors(name=name)) is ok


@pytest.mark.parametrize(("description", "ok"), [("", True), ("x" * 2000, True), ("x" * 2001, False)])
def test_description_rule(description: str, ok: bool) -> None:
    assert ("description" not in field_errors(description=description)) is ok


def test_tags_limit_is_twenty() -> None:
    assert field_errors(tags=[f"t{i}" for i in range(20)]) == {}
    assert "tags" in field_errors(tags=[f"t{i}" for i in range(21)])


@pytest.mark.parametrize(
    ("tag", "ok"),
    [("billing", True), ("a" * 32, True), ("a" * 33, False), ("Billing", False), ("-a", False), ("", False)],
)
def test_tag_rule_names_the_offending_index(tag: str, ok: bool) -> None:
    errors = field_errors(tags=["fine", tag])
    assert ("tags[1]" not in errors) is ok


@pytest.mark.parametrize("visibility", ["private", "tenant"])
def test_visibility_without_policy(visibility: str) -> None:
    assert field_errors(visibility=visibility) == {}


def test_unknown_visibility_fails() -> None:
    assert "visibility" in field_errors(visibility="public")


def test_restricted_requires_policy_id() -> None:
    assert "policy_id" in field_errors(visibility="restricted", policy_id=None)
    assert field_errors(visibility="restricted", policy_id="7b0d6f3e-0000-4000-8000-000000000000") == {}


def test_meta_must_be_object() -> None:
    assert "meta" in field_errors(meta=["x"])


def test_meta_limit_is_16_kb() -> None:
    under = {"k": "x" * (16 * 1024 - 10)}
    over = {"k": "x" * (16 * 1024)}
    assert field_errors(meta=under) == {}
    assert "meta" in field_errors(meta=over)


def test_meta_limit_counts_utf8_bytes() -> None:
    assert "meta" in field_errors(meta={"k": "é" * (9 * 1024)})


def test_canonical_json_sorts_keys_without_whitespace() -> None:
    assert canonical_json({"b": 1, "a": {"d": [1, 2], "c": "é"}}) == '{"a":{"c":"é","d":[1,2]},"b":1}'.encode()


def test_hash_ignores_key_order() -> None:
    a = {"model": "m", "system_prompt": "p", "model_config": {"x": 1, "y": 2}}
    b = {"model_config": {"y": 2, "x": 1}, "system_prompt": "p", "model": "m"}
    assert content_hash("agent", a) == content_hash("agent", b)


def test_hash_changes_with_any_change() -> None:
    base = content_hash("agent", VALID_AGENT)
    changed = copy.deepcopy(VALID_AGENT)
    changed["runtime_config"]["timeout_seconds"] = 901
    assert content_hash("agent", changed) != base
    assert content_hash("other", VALID_AGENT) != base


def test_hash_is_sha256_of_canonical_type_and_spec() -> None:
    expected = hashlib.sha256(
        json.dumps({"type": "agent", "spec": VALID_AGENT}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert content_hash("agent", VALID_AGENT) == expected


def test_skill_hash_uses_content_sha256_spec() -> None:
    digest = hashlib.sha256(b"zip").hexdigest()
    expected = hashlib.sha256(
        canonical_json({"type": "skill", "spec": {"content_sha256": digest}})
    ).hexdigest()
    assert content_hash("skill", {"content_sha256": digest}) == expected
