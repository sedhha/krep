import base64
import binascii
import json
from typing import Any, cast

from krep.api.errors import ApiError

MAX_PRINCIPAL_BYTES = 4096


def _invalid() -> ApiError:
    return ApiError(400, "principal_invalid", "X-Principal must be base64url JSON object up to 4 KB")


def decode_principal(header: str | None) -> dict[str, Any] | None:
    if header is None:
        return None
    if len(header) > MAX_PRINCIPAL_BYTES * 2:
        raise _invalid()
    try:
        raw = base64.urlsafe_b64decode(header + "=" * (-len(header) % 4))
        value: Any = json.loads(raw)
    except (binascii.Error, ValueError):
        raise _invalid() from None
    if len(raw) > MAX_PRINCIPAL_BYTES or not isinstance(value, dict):
        raise _invalid()
    principal = cast("dict[str, Any]", value)
    principal_id = principal.get("id")
    if not isinstance(principal_id, str) or not principal_id:
        raise ApiError(400, "principal_id_required", "principal must include a string id")
    return principal
