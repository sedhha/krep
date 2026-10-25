import json
import math
import re
from typing import Any, cast

MAX_NODES = 100
MAX_DEPTH = 8
MAX_SEGMENTS = 8
MAX_SEGMENT_LENGTH = 128
MAX_LITERAL_LENGTH = 256
MAX_LIST_VALUES = 50

ROOTS = ("token", "principal")
CMP_OPS = ("==", "!=", "<", "<=", ">", ">=")
STRING_OPS = {"starts_with": "startsWith", "ends_with": "endsWith"}
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class PolicyError(Exception):
    pass


class PolicyParseError(PolicyError):
    def __init__(self, line: int, column: int, message: str):
        super().__init__(f"{message} (line {line}, column {column})")
        self.line = line
        self.column = column
        self.message = message


class PolicyTooLarge(PolicyError):
    def __init__(self, nodes: int, max: int):
        super().__init__(f"policy has {nodes} nodes, maximum is {max}")
        self.nodes = nodes
        self.max = max


class PolicyInvalid(PolicyError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _as_dict(value: object) -> dict[str, Any] | None:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _as_list(value: object) -> list[Any] | None:
    return cast("list[Any]", value) if isinstance(value, list) else None


def _count_nodes(ast: object) -> int:
    count = 0
    stack: list[object] = [ast]
    while stack:
        node = _as_dict(stack.pop())
        if node is None:
            continue
        count += 1
        op = node.get("op")
        if op in ("and", "or"):
            args = _as_list(node.get("args"))
            if args is not None:
                stack.extend(args)
        elif op == "not":
            stack.append(node.get("arg"))
    return count


def _check_keys(node: dict[str, Any], expected: set[str]) -> None:
    if set(node) != expected:
        raise PolicyInvalid(
            f"node '{node.get('op')}' must have exactly the keys {sorted(expected)}"
        )


def _check_path(raw: object) -> None:
    path = _as_dict(raw)
    if path is None or set(path) != {"root", "segments"}:
        raise PolicyInvalid("path must be an object with 'root' and 'segments'")
    if path["root"] not in ROOTS:
        raise PolicyInvalid("path root must be 'token' or 'principal'")
    segments = _as_list(path["segments"])
    if segments is None:
        raise PolicyInvalid("path segments must be a list")
    if len(segments) > MAX_SEGMENTS:
        raise PolicyInvalid(f"path has more than {MAX_SEGMENTS} segments")
    for segment in segments:
        if not isinstance(segment, str):
            raise PolicyInvalid("path segments must be strings")
        if not 1 <= len(segment) <= MAX_SEGMENT_LENGTH:
            raise PolicyInvalid(
                f"path segment must be 1-{MAX_SEGMENT_LENGTH} characters"
            )
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in segment):
            raise PolicyInvalid("path segment contains a control character")
        _check_text(segment)


def _check_text(text: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise PolicyInvalid("text contains an invalid unicode character") from None
    if "\x00" in text:
        raise PolicyInvalid("text contains a NUL character")


def _check_value(raw: object) -> None:
    value = _as_dict(raw)
    if value is None or len(value) != 1:
        raise PolicyInvalid("value must be {'lit': ...} or {'var': 'tenant_id'}")
    if "var" in value:
        if value["var"] != "tenant_id":
            raise PolicyInvalid("the only variable is 'tenant_id'")
        return
    if "lit" not in value:
        raise PolicyInvalid("value must be {'lit': ...} or {'var': 'tenant_id'}")
    literal = value["lit"]
    if literal is None or isinstance(literal, bool):
        return
    if isinstance(literal, int):
        return
    if isinstance(literal, float):
        if not math.isfinite(literal):
            raise PolicyInvalid("number literals must be finite")
        return
    if isinstance(literal, str):
        if len(literal) > MAX_LITERAL_LENGTH:
            raise PolicyInvalid(
                f"string literals are limited to {MAX_LITERAL_LENGTH} characters"
            )
        _check_text(literal)
        return
    raise PolicyInvalid("literal must be a string, number, boolean or null")


def _check_string_value(raw: object) -> None:
    _check_value(raw)
    value = _as_dict(raw) or {}
    if not isinstance(value.get("lit"), str):
        raise PolicyInvalid("a string literal is required")


def _validate_node(raw: object, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise PolicyInvalid(f"policy depth exceeds {MAX_DEPTH}")
    node = _as_dict(raw)
    if node is None:
        raise PolicyInvalid("every node must be an object")
    op = node.get("op")
    if op in ("and", "or"):
        _check_keys(node, {"op", "args"})
        args = _as_list(node["args"])
        if not args:
            raise PolicyInvalid(f"'{op}' needs at least one argument")
        for arg in args:
            _validate_node(arg, depth + 1)
    elif op == "not":
        _check_keys(node, {"op", "arg"})
        _validate_node(node["arg"], depth + 1)
    elif op == "cmp":
        _check_keys(node, {"op", "path", "cmp", "value"})
        if node["cmp"] not in CMP_OPS:
            raise PolicyInvalid(f"comparison must be one of {', '.join(CMP_OPS)}")
        _check_path(node["path"])
        _check_value(node["value"])
    elif op == "member":
        _check_keys(node, {"op", "path", "value"})
        _check_path(node["path"])
        _check_value(node["value"])
    elif op == "in_list":
        _check_keys(node, {"op", "path", "values"})
        _check_path(node["path"])
        values = _as_list(node["values"])
        if not values:
            raise PolicyInvalid("'in_list' needs at least one value")
        if len(values) > MAX_LIST_VALUES:
            raise PolicyInvalid(f"'in' lists are limited to {MAX_LIST_VALUES} values")
        for value in values:
            _check_value(value)
    elif op in STRING_OPS:
        _check_keys(node, {"op", "path", "value"})
        _check_path(node["path"])
        _check_string_value(node["value"])
    elif op == "has":
        _check_keys(node, {"op", "path"})
        _check_path(node["path"])
    else:
        raise PolicyInvalid(f"unknown node op: {op!r}")


def validate_ast(ast: dict[str, Any]) -> int:
    nodes = _count_nodes(ast)
    if nodes > MAX_NODES:
        raise PolicyTooLarge(nodes, MAX_NODES)
    _validate_node(ast, 1)
    return nodes


def path_source(path: dict[str, Any]) -> str:
    parts = [path["root"]]
    for segment in path["segments"]:
        if IDENT_RE.fullmatch(segment):
            parts.append(f".{segment}")
        else:
            parts.append(f"[{_string_source(segment)}]")
    return "".join(parts)


def _string_source(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _value_source(value: dict[str, Any]) -> str:
    if "var" in value:
        return f"var.{value['var']}"
    literal = value["lit"]
    if literal is None:
        return "null"
    if literal is True:
        return "true"
    if literal is False:
        return "false"
    if isinstance(literal, str):
        return _string_source(literal)
    return repr(literal)


def to_source(ast: dict[str, Any]) -> str:
    op = ast["op"]
    if op in ("and", "or"):
        joiner = " && " if op == "and" else " || "
        parts: list[str] = []
        for arg in ast["args"]:
            text = to_source(arg)
            parts.append(f"({text})" if arg["op"] in ("and", "or") else text)
        return joiner.join(parts)
    if op == "not":
        return f"!({to_source(ast['arg'])})"
    path = path_source(ast["path"]) if "path" in ast else ""
    if op == "cmp":
        return f"{path} {ast['cmp']} {_value_source(ast['value'])}"
    if op == "member":
        return f"{_value_source(ast['value'])} in {path}"
    if op == "in_list":
        values = ", ".join(_value_source(v) for v in ast["values"])
        return f"{path} in [{values}]"
    if op in STRING_OPS:
        return f"{path}.{STRING_OPS[op]}({_value_source(ast['value'])})"
    return f"has({path})"
