import re

MAX_TOKENS = 12
MAX_QUERY_CHARS = 100
MAX_TERMS = 30
MAX_PHRASE_WORDS = 3

_NON_WORD = re.compile(r"\W+")


def normalise(q: str) -> str:
    tokens = _NON_WORD.sub(" ", q.lower()).split()[:MAX_TOKENS]
    return " ".join(tokens)[:MAX_QUERY_CHARS].rstrip()


def expand(q_norm: str, groups: list[list[str]]) -> list[str]:
    tokens = q_norm.split()
    terms = list(tokens)
    index: dict[str, list[str]] = {}
    for group in groups:
        for member in group:
            index.setdefault(member, []).extend(group)
    for size in range(1, MAX_PHRASE_WORDS + 1):
        for start in range(len(tokens) - size + 1):
            phrase = " ".join(tokens[start : start + size])
            terms.extend(other for other in index.get(phrase, []) if other != phrase)
    return list(dict.fromkeys(terms))[:MAX_TERMS]


def build_tsquery(terms: list[str]) -> str | None:
    parts = [
        words[0] if len(words) == 1 else "(" + " <-> ".join(words) + ")"
        for words in (term.split() for term in terms)
        if words
    ]
    return " | ".join(parts) or None
