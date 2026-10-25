import json
from pathlib import Path
from typing import Any, cast

from lark import Lark, Token, Transformer
from lark.exceptions import (
    UnexpectedCharacters,
    UnexpectedInput,
    UnexpectedToken,
    VisitError,
)

from krep.policy.ast import (
    STRING_OPS,
    PolicyInvalid,
    PolicyParseError,
    validate_ast,
)

_GRAMMAR = Path(__file__).with_name("grammar.lark")
_PARSER: Any = Lark(_GRAMMAR.read_text(), parser="lalr", start="start")
_METHOD_OPS = {name: op for op, name in STRING_OPS.items()}


def _error_at(token: Token, message: str) -> PolicyParseError:
    return PolicyParseError(token.line or 1, token.column or 1, message)


class _ToAst(Transformer[Token, dict[str, Any]]):
    def start(self, children: list[Any]) -> Any:
        return children[0]

    def or_(self, children: list[Any]) -> Any:
        return {"op": "or", "args": list(children)}

    def and_(self, children: list[Any]) -> Any:
        return {"op": "and", "args": list(children)}

    def not_(self, children: list[Any]) -> Any:
        return {"op": "not", "arg": children[0]}

    def cmp(self, children: list[Any]) -> Any:
        path, operator, value = children
        return {"op": "cmp", "path": path, "cmp": str(operator), "value": value}

    def member(self, children: list[Any]) -> Any:
        value, _, path = children
        return {"op": "member", "path": path, "value": value}

    def in_list(self, children: list[Any]) -> Any:
        path, _, *values = children
        return {"op": "in_list", "path": path, "values": values}

    def call(self, children: list[Any]) -> Any:
        path, method, string = children
        op = _METHOD_OPS.get(str(method))
        if op is None:
            raise _error_at(method, f"unknown method '{method}'")
        return {"op": op, "path": path, "value": self._string(string)}

    def has(self, children: list[Any]) -> Any:
        return {"op": "has", "path": children[1]}

    def root_path(self, children: list[Any]) -> Any:
        return {"root": str(children[0]), "segments": []}

    def dot_segment(self, children: list[Any]) -> Any:
        path, segment = children
        return {"root": path["root"], "segments": [*path["segments"], str(segment)]}

    def key_segment(self, children: list[Any]) -> Any:
        path, key = children
        return {
            "root": path["root"],
            "segments": [*path["segments"], json.loads(key)],
        }

    def lit_string(self, children: list[Any]) -> Any:
        return self._string(children[0])

    def lit_number(self, children: list[Any]) -> Any:
        text = str(children[0])
        try:
            number = float(text) if any(c in text for c in ".eE") else int(text)
        except ValueError:
            raise _error_at(children[0], "number is too large") from None
        return {"lit": number}

    def lit_true(self, children: list[Any]) -> Any:
        return {"lit": True}

    def lit_false(self, children: list[Any]) -> Any:
        return {"lit": False}

    def lit_null(self, children: list[Any]) -> Any:
        return {"lit": None}

    def lit_var(self, children: list[Any]) -> Any:
        return {"var": "tenant_id"}

    @staticmethod
    def _string(token: Token) -> dict[str, Any]:
        return {"lit": json.loads(token)}


def _end_position(source: str) -> tuple[int, int]:
    line = source.count("\n") + 1
    column = len(source) - (source.rfind("\n") + 1) + 1
    return line, column


def _syntax_error(exc: UnexpectedInput, source: str) -> PolicyParseError:
    if isinstance(exc, UnexpectedToken):
        token = cast(Token, cast(Any, exc).token)
        if token.type == "$END":
            line, column = _end_position(source)
            return PolicyParseError(line, column, "unexpected end of rule")
        return PolicyParseError(exc.line, exc.column, f"unexpected '{token}'")
    if isinstance(exc, UnexpectedCharacters):
        return PolicyParseError(
            exc.line, exc.column, f"unexpected character {cast(Any, exc).char!r}"
        )
    line, column = _end_position(source)
    return PolicyParseError(line, column, "unexpected end of rule")


def parse(source: str) -> dict[str, Any]:
    try:
        tree = _PARSER.parse(source)
        ast = _ToAst().transform(tree)
    except UnexpectedInput as exc:
        raise _syntax_error(exc, source) from None
    except VisitError as exc:
        if isinstance(exc.orig_exc, PolicyParseError):
            raise exc.orig_exc from None
        raise
    except RecursionError:
        raise PolicyInvalid("rule is nested too deeply") from None
    validate_ast(ast)
    return ast
