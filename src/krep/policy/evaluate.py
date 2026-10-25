from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from krep.policy.ast import path_source, to_source
from krep.policy.compile import compile_ast


@dataclass
class LeafResult:
    text: str
    result: bool
    note: str | None = None


async def evaluate(
    conn: psycopg.AsyncConnection,
    compiled_path: str,
    doc: dict[str, Any],
    tenant_id: UUID | str,
) -> bool:
    cursor = await conn.execute(
        "SELECT jsonb_path_match(%s, %s::jsonpath, %s, true)",
        (Jsonb(doc), compiled_path, Jsonb({"tenant_id": str(tenant_id)})),
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


def _leaves(node: dict[str, Any], negated: bool = False) -> list[tuple[dict[str, Any], bool]]:
    op = node["op"]
    if op in ("and", "or"):
        return [leaf for arg in node["args"] for leaf in _leaves(arg, negated)]
    if op == "not":
        return _leaves(node["arg"], True)
    return [(node, negated)]


async def evaluate_leaves(
    conn: psycopg.AsyncConnection,
    ast: dict[str, Any],
    doc: dict[str, Any],
    tenant_id: UUID,
) -> list[LeafResult]:
    results: list[LeafResult] = []
    for leaf, negated in _leaves(ast):
        satisfied = await evaluate(conn, compile_ast(leaf), doc, tenant_id)
        results.append(
            LeafResult(
                to_source(leaf), satisfied, "negated in the rule" if negated else None
            )
        )
    return results


_MISSING = object()


def _lookup(doc: dict[str, Any], path: dict[str, Any]) -> Any:
    current: Any = doc.get(path["root"])
    for segment in path["segments"]:
        if not isinstance(current, dict):
            return _MISSING
        node = cast("dict[str, Any]", current)
        if segment not in node:
            return _MISSING
        current = node[segment]
    return current


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    return "object"


def _literals(leaf: dict[str, Any]) -> list[dict[str, Any]]:
    if leaf["op"] == "in_list":
        return leaf["values"]
    if leaf["op"] in ("starts_with", "ends_with", "cmp", "member"):
        return [leaf["value"]]
    return []


def _literal_type(value: dict[str, Any]) -> str:
    return "string" if "var" in value else _type_name(value["lit"])


def _preview(value: Any) -> str:
    return f'"{value}"' if isinstance(value, str) else str(value)


def _type_warning(path_text: str, claim: Any, literal_type: str) -> str | None:
    if isinstance(claim, list):
        items = cast("list[Any]", claim)
        element_types = {_type_name(item) for item in items}
        if not items or literal_type in element_types:
            return None
        names = sorted(element_types)
        kind = f"{names[0]}s" if len(names) == 1 else "mixed types"
        return f"{path_text} is a list of {kind} but is compared with a {literal_type}"
    actual = _type_name(claim)
    if actual == literal_type:
        return None
    return (
        f"{path_text} is a {actual} ({_preview(claim)}) "
        f"but is compared with a {literal_type}"
    )


def _has_groups_overage(doc: dict[str, Any]) -> bool:
    token: Any = doc.get("token")
    if not isinstance(token, dict):
        return False
    names: Any = cast("dict[str, Any]", token).get("_claim_names")
    return isinstance(names, (dict, list)) and "groups" in cast("Any", names)


def warnings_for(ast: dict[str, Any], doc: dict[str, Any]) -> list[str]:
    warnings: list[str] = []

    def add(message: str | None) -> None:
        if message and message not in warnings:
            warnings.append(message)

    for leaf, _ in _leaves(ast):
        path = leaf["path"]
        path_text = path_source(path)
        claim = _lookup(doc, path)
        if claim is _MISSING:
            add(f"{path_text} is absent from the sample")
            continue
        for literal in _literals(leaf):
            add(_type_warning(path_text, claim, _literal_type(literal)))
    if _has_groups_overage(doc):
        add(
            "token._claim_names lists groups: the identity provider omitted the "
            "groups claim (overage), so rules over groups cannot match"
        )
    return warnings
