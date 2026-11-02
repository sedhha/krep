import hmac

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from krep.api.errors import ApiError
from krep.config import get_settings

router = APIRouter()

_BEARER = "bearer "


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    expected = get_settings().metrics_token
    if not expected:
        raise ApiError(404, "not_found", "not found")
    header = request.headers.get("authorization", "")
    supplied = header[len(_BEARER) :] if header.lower().startswith(_BEARER) else ""
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise ApiError(401, "unauthenticated", "invalid metrics token")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
