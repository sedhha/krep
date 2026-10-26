from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from psycopg import AsyncConnection

from krep.api.errors import ApiError
from krep.db.tenant import tenant_transaction
from krep.identity.resolve import Caller, resolve_caller


async def get_caller(request: Request) -> Caller:
    caller = await resolve_caller(request.app.state.pool, request.headers)
    request.state.tenant_id = str(caller.tenant_id)
    request.state.user_id = caller.user_id
    return caller


async def require_write(caller: Annotated[Caller, Depends(get_caller)]) -> Caller:
    if not caller.can_write:
        raise ApiError(403, "forbidden", "write permission required")
    return caller


async def require_admin(caller: Annotated[Caller, Depends(get_caller)]) -> Caller:
    if not caller.can_admin:
        raise ApiError(403, "forbidden", "admin permission required")
    return caller


async def db(
    request: Request, caller: Annotated[Caller, Depends(get_caller)]
) -> AsyncGenerator[AsyncConnection]:
    async with tenant_transaction(request.app.state.pool, caller.tenant_id) as conn:
        yield conn
