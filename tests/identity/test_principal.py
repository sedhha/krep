import pytest

from krep.api.errors import ApiError
from krep.identity.principal import decode_principal
from tests.identity.conftest import b64url


def test_absent_header_is_none() -> None:
    assert decode_principal(None) is None


def test_decodes_object_with_id() -> None:
    value = {"id": "user-123", "roles": ["support"], "clearance": 3}
    assert decode_principal(b64url(value)) == value


def test_accepts_padded_base64url() -> None:
    import base64

    raw = base64.urlsafe_b64encode(b'{"id":"a"}').decode()
    assert decode_principal(raw) == {"id": "a"}


@pytest.mark.parametrize("value", [{"roles": []}, {"id": 5}, {"id": ""}, {"id": None}])
def test_missing_or_non_string_id(value: dict[str, object]) -> None:
    with pytest.raises(ApiError) as exc:
        decode_principal(b64url(value))
    assert (exc.value.status, exc.value.error) == (400, "principal_id_required")


@pytest.mark.parametrize("header", ["!!!not-base64!!!", b64url(b"\xff\xfe"), b64url(b"{nope")])
def test_invalid_encoding_or_json(header: str) -> None:
    with pytest.raises(ApiError) as exc:
        decode_principal(header)
    assert (exc.value.status, exc.value.error) == (400, "principal_invalid")


@pytest.mark.parametrize("value", [["id"], "id", 5, None])
def test_non_object(value: object) -> None:
    with pytest.raises(ApiError) as exc:
        decode_principal(b64url(value))
    assert (exc.value.status, exc.value.error) == (400, "principal_invalid")


def test_oversize() -> None:
    with pytest.raises(ApiError) as exc:
        decode_principal(b64url({"id": "a", "pad": "x" * 4096}))
    assert (exc.value.status, exc.value.error) == (400, "principal_invalid")


def test_exactly_at_limit_is_accepted() -> None:
    overhead = len(b'{"id":"a","pad":""}')
    body = b'{"id":"a","pad":"' + b"x" * (4096 - overhead) + b'"}'
    assert len(body) == 4096
    assert decode_principal(b64url(body)) == {"id": "a", "pad": "x" * (4096 - overhead)}
