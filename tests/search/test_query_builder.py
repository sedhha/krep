import pytest

from krep.search.query import build_tsquery, expand, normalise


def test_normalise_lowercases_and_strips_symbols() -> None:
    assert normalise("  Refund | ) & ! Money-Back  ") == "refund money back"


def test_normalise_keeps_underscore_and_digits() -> None:
    assert normalise("agent_v2!") == "agent_v2"


def test_normalise_caps_tokens_at_12() -> None:
    assert normalise(" ".join(f"w{i}" for i in range(20))) == " ".join(f"w{i}" for i in range(12))


def test_normalise_caps_length_at_100() -> None:
    assert len(normalise(" ".join(["abcdefghij"] * 12))) <= 100


def test_normalise_symbols_only_is_empty() -> None:
    assert normalise("'\"; -- | ) & !") == ""


def test_expand_without_groups_returns_tokens() -> None:
    assert expand("money back returned", []) == ["money", "back", "returned"]


def test_expand_is_symmetric() -> None:
    groups = [["refund", "money back", "reimbursement"]]
    assert expand("reimbursement", groups) == ["reimbursement", "refund", "money back"]
    assert expand("refund", groups) == ["refund", "money back", "reimbursement"]


def test_expand_matches_phrase_members() -> None:
    groups = [["refund", "money back"]]
    assert "refund" in expand("money back", groups)


def test_expand_is_not_transitive() -> None:
    groups = [["a1", "b1"], ["b1", "c1"]]
    assert "c1" not in expand("a1", groups)


def test_expand_dedupes_and_caps_at_30() -> None:
    groups = [[f"t{i}" for i in range(10)] for _ in range(1)]
    big = [[f"x{i}", *[f"y{i}_{j}" for j in range(9)]] for i in range(12)]
    out = expand(" ".join(f"x{i}" for i in range(12)), big)
    assert len(out) == 30
    assert len(set(out)) == 30
    assert expand("t0", groups).count("t1") == 1


def test_build_tsquery_joins_with_or_and_phrases() -> None:
    assert build_tsquery(["refund", "money back"]) == "refund | (money <-> back)"


def test_build_tsquery_empty_is_none() -> None:
    assert build_tsquery([]) is None


@pytest.mark.parametrize("raw", ["refund | ) & !", "'\"; --", "the a of", "", "   ", "!!!"])
def test_ac25_hostile_inputs_build_without_error(raw: str) -> None:
    terms = expand(normalise(raw), [])
    tsq = build_tsquery(terms)
    assert tsq is None or all(ch.isalnum() or ch in "_ |()<->" for ch in tsq)
