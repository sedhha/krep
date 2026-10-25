import json
import re
from typing import Any

from krep.policy.ast import validate_ast

COMPILER_VERSION = 1

_REGEX_META = re.compile(r"[\\.\[\]{}()*+?^$|]")


def _quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _path(path: dict[str, Any]) -> str:
    return "$" + "".join(f".{_quote(s)}" for s in [path["root"], *path["segments"]])


def _value(value: dict[str, Any]) -> str:
    if "var" in value:
        return "$tenant_id"
    return json.dumps(value["lit"], ensure_ascii=False)


def _exists(node: dict[str, Any], predicate: str) -> str:
    return f"exists({_path(node['path'])}[*] ? ({predicate}))"


def _compile(node: dict[str, Any]) -> str:
    op = node["op"]
    if op in ("and", "or"):
        parts = [
            f"({_compile(arg)})" if arg["op"] in ("and", "or") else _compile(arg)
            for arg in node["args"]
        ]
        return (" && " if op == "and" else " || ").join(parts)
    if op == "not":
        return f"!({_compile(node['arg'])})"
    if op == "has":
        return f"exists({_path(node['path'])})"
    if op == "member":
        return _exists(node, f"@ == {_value(node['value'])}")
    if op == "cmp":
        if node["cmp"] == "!=":
            return f"!({_exists(node, f'@ == {_value(node['value'])}')})"
        return _exists(node, f"@ {node['cmp']} {_value(node['value'])}")
    if op == "in_list":
        alternatives = " || ".join(f"@ == {_value(v)}" for v in node["values"])
        return _exists(node, alternatives)
    text = node["value"]["lit"]
    if op == "starts_with":
        return _exists(node, f"@ starts with {_quote(text)}")
    pattern = _REGEX_META.sub(lambda m: "\\" + m.group(0), text) + "$"
    return _exists(node, f"@ like_regex {_quote(pattern)}")


def compile_ast(ast: dict[str, Any]) -> str:
    validate_ast(ast)
    return _compile(ast)
