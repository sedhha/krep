import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import celpy
from celpy.celparser import CELParseError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
VISIBILITIES = ("private", "tenant", "restricted")
MAX_NAME = 120
MAX_DESCRIPTION = 2000
MAX_TAGS = 20
MAX_META_BYTES = 16 * 1024

_CEL: Any = celpy.Environment()


@dataclass(frozen=True)
class FieldError:
    field: str
    message: str


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def content_hash(type: str, spec: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json({"type": type, "spec": spec})).hexdigest()


def _non_blank_string(spec: dict[str, Any], key: str, errors: list[FieldError]) -> None:
    value = spec.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(FieldError(f"spec.{key}", "required non-empty string"))


def _optional_object(spec: dict[str, Any], key: str, errors: list[FieldError]) -> None:
    if key in spec and not isinstance(spec[key], dict):
        errors.append(FieldError(f"spec.{key}", "must be an object"))


def _json_schema(spec: dict[str, Any], key: str, errors: list[FieldError]) -> None:
    if key not in spec:
        return
    schema: Any = spec[key]
    if not isinstance(schema, dict):
        errors.append(FieldError(f"spec.{key}", "must be a JSON Schema object"))
        return
    try:
        Draft202012Validator.check_schema(cast("dict[str, Any]", schema))
    except SchemaError as exc:
        errors.append(FieldError(f"spec.{key}", f"invalid JSON Schema: {exc.message}"))


def _hitl_rules(spec: dict[str, Any], errors: list[FieldError]) -> None:
    if "hitl_rules" not in spec:
        return
    rules: Any = spec["hitl_rules"]
    if not isinstance(rules, list):
        errors.append(FieldError("spec.hitl_rules", "must be a list"))
        return
    for i, rule in enumerate(cast("list[Any]", rules)):
        path = f"spec.hitl_rules[{i}]"
        if not isinstance(rule, dict):
            errors.append(FieldError(path, "must be an object"))
            continue
        item = cast("dict[str, Any]", rule)
        when = item.get("when")
        if not isinstance(when, str) or not when.strip():
            errors.append(FieldError(f"{path}.when", "required non-empty CEL expression"))
        else:
            try:
                _CEL.compile(when)
            except CELParseError as exc:
                errors.append(FieldError(f"{path}.when", f"invalid CEL: {exc.args[0]}"))
        action = item.get("action")
        if not isinstance(action, str) or not action.strip():
            errors.append(FieldError(f"{path}.action", "required non-empty string"))


def validate_agent_spec(raw: Any) -> list[FieldError]:
    errors: list[FieldError] = []
    if not isinstance(raw, dict):
        return [FieldError("spec", "must be an object")]
    spec = cast("dict[str, Any]", raw)
    _non_blank_string(spec, "model", errors)
    _non_blank_string(spec, "system_prompt", errors)
    _optional_object(spec, "model_config", errors)
    _optional_object(spec, "runtime_config", errors)
    _json_schema(spec, "input_schema", errors)
    _json_schema(spec, "output_schema", errors)
    _hitl_rules(spec, errors)
    return errors


VALIDATORS: dict[str, Callable[[dict[str, Any]], list[FieldError]]] = {
    "agent": validate_agent_spec,
}


def validate_spec(type: str, spec: dict[str, Any]) -> list[FieldError]:
    return VALIDATORS[type](spec)


def validate_resource_fields(
    name: str,
    slug: str,
    description: str,
    tags: list[str],
    visibility: str,
    policy_id: Any,
    meta: Any,
) -> list[FieldError]:
    errors: list[FieldError] = []
    if not SLUG_RE.fullmatch(slug):
        errors.append(FieldError("slug", "must match ^[a-z0-9][a-z0-9-]{1,62}$"))
    if not 1 <= len(name) <= MAX_NAME:
        errors.append(FieldError("name", f"must be 1-{MAX_NAME} characters"))
    if len(description) > MAX_DESCRIPTION:
        errors.append(FieldError("description", f"must be at most {MAX_DESCRIPTION} characters"))
    if len(tags) > MAX_TAGS:
        errors.append(FieldError("tags", f"at most {MAX_TAGS} tags"))
    errors.extend(
        FieldError(f"tags[{i}]", "must match ^[a-z0-9][a-z0-9-]{0,31}$")
        for i, tag in enumerate(tags)
        if not TAG_RE.fullmatch(tag)
    )
    if visibility not in VISIBILITIES:
        errors.append(FieldError("visibility", f"must be one of {', '.join(VISIBILITIES)}"))
    elif visibility == "restricted" and policy_id is None:
        errors.append(FieldError("policy_id", "required when visibility is restricted"))
    if not isinstance(meta, dict):
        errors.append(FieldError("meta", "must be an object"))
    elif len(canonical_json(meta)) > MAX_META_BYTES:
        errors.append(FieldError("meta", f"must be at most {MAX_META_BYTES} bytes"))
    return errors
