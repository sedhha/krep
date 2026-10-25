import json
from typing import Any

_CMP_PHRASES = {
    "==": "is",
    "!=": "is not",
    "<": "is less than",
    "<=": "is at most",
    ">": "is greater than",
    ">=": "is at least",
}
_STRING_PHRASES = {"starts_with": "starts with", "ends_with": "ends with"}


def _path(path: dict[str, Any]) -> str:
    segments = ".".join(path["segments"])
    if path["root"] == "token":
        return segments
    return f"principal.{segments}" if segments else "principal"


def _value(value: dict[str, Any]) -> str:
    if "var" in value:
        return "the tenant id"
    return json.dumps(value["lit"], ensure_ascii=False)


def _describe(node: dict[str, Any], top: bool) -> str:
    op = node["op"]
    if op in ("and", "or"):
        word = op.upper()
        joiner = f", {word} " if top else f" {word} "
        text = joiner.join(_describe(arg, False) for arg in node["args"])
        return text if top or len(node["args"]) == 1 else f"({text})"
    if op == "not":
        child = node["arg"]
        text = _describe(child, False)
        if child["op"] in ("and", "or") and len(child["args"]) == 1:
            text = f"({text})"
        return f"NOT {text}"
    path = _path(node["path"])
    if op == "cmp":
        return f"{path} {_CMP_PHRASES[node['cmp']]} {_value(node['value'])}"
    if op == "member":
        return f"{path} contains {_value(node['value'])}"
    if op == "in_list":
        values = ", ".join(_value(v) for v in node["values"])
        return f"{path} is one of {values}"
    if op in _STRING_PHRASES:
        return f"{path} {_STRING_PHRASES[op]} {_value(node['value'])}"
    return f"{path} is present"


def summarize(ast: dict[str, Any]) -> str:
    return f"Visible when: {_describe(ast, True)}."
