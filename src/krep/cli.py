import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from uuid import UUID

from psycopg import AsyncConnection

from krep.policy.ast import PolicyError, PolicyInvalid, PolicyParseError, PolicyTooLarge
from krep.policy.compile import COMPILER_VERSION, compile_ast
from krep.policy.parser import parse
from krep.policy.store import write_policy

RESERVED_POLICIES = ("registry-admins", "registry-writers")
CLI_USER = "ops:cli"


def _tenant(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a valid tenant uuid") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="krep")
    groups = parser.add_subparsers(dest="group", required=True)

    tenant = groups.add_parser("tenant").add_subparsers(dest="command", required=True)
    init = tenant.add_parser("init", help="create the reserved policies for a tenant")
    init.add_argument("--tenant", type=_tenant, required=True)
    init.add_argument("--admin-rule", required=True)
    init.add_argument("--writer-rule", required=True)

    policy = groups.add_parser("policy").add_subparsers(dest="command", required=True)
    reset = policy.add_parser("reset", help="replace a reserved policy rule")
    reset.add_argument("name", choices=RESERVED_POLICIES)
    reset.add_argument("--tenant", type=_tenant, required=True)
    reset.add_argument("--rule", required=True)
    policy.add_parser("recompile", help="rewrite compiled_path for stale compiler versions")
    return parser


def _error(exc: PolicyError) -> str:
    if isinstance(exc, PolicyParseError):
        return f"policy_parse_error at line {exc.line}, column {exc.column}: {exc}"
    if isinstance(exc, PolicyTooLarge):
        return f"policy_too_large: {exc}"
    if isinstance(exc, PolicyInvalid):
        return f"policy_invalid: {exc}"
    return f"policy_error: {exc}"


async def _scope(conn: AsyncConnection, tenant_id: UUID) -> None:
    await conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))


async def _tenant_init(conn: AsyncConnection, tenant_id: UUID, admin: str, writer: str) -> None:
    rules = {"registry-admins": parse(admin), "registry-writers": parse(writer)}
    async with conn.transaction():
        await _scope(conn, tenant_id)
        await conn.execute(
            "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING", (tenant_id,)
        )
        for name, ast in rules.items():
            cur = await conn.execute(
                "SELECT 1 FROM access_policies WHERE tenant_id = %s AND name = %s",
                (tenant_id, name),
            )
            if await cur.fetchone() is None:
                await write_policy(conn, tenant_id, name, ast, CLI_USER, reserved=True)


async def _policy_reset(conn: AsyncConnection, tenant_id: UUID, name: str, rule: str) -> None:
    ast = parse(rule)
    async with conn.transaction():
        await _scope(conn, tenant_id)
        await conn.execute(
            "INSERT INTO tenants (tenant_id) VALUES (%s) ON CONFLICT DO NOTHING", (tenant_id,)
        )
        await write_policy(conn, tenant_id, name, ast, CLI_USER, reserved=True)


async def _recompile(conn: AsyncConnection) -> int:
    cur = await conn.execute("SELECT tenant_id FROM tenants ORDER BY tenant_id")
    tenants = [row[0] for row in await cur.fetchall()]
    rewritten = 0
    for tenant_id in tenants:
        async with conn.transaction():
            await _scope(conn, tenant_id)
            cur = await conn.execute(
                "SELECT id, ast FROM access_policies WHERE compiler_version < %s FOR UPDATE",
                (COMPILER_VERSION,),
            )
            for policy_id, ast in await cur.fetchall():
                await conn.execute(
                    "UPDATE access_policies SET compiled_path = %s::jsonpath, "
                    "compiler_version = %s WHERE id = %s",
                    (compile_ast(ast), COMPILER_VERSION, policy_id),
                )
                rewritten += 1
    return rewritten


async def _run(args: argparse.Namespace) -> None:
    url = os.environ["KREP_MIGRATION_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    async with await AsyncConnection.connect(url) as conn:
        if args.group == "tenant":
            await _tenant_init(conn, args.tenant, args.admin_rule, args.writer_rule)
            print(f"tenant {args.tenant} initialised")
        elif args.command == "reset":
            await _policy_reset(conn, args.tenant, args.name, args.rule)
            print(f"{args.name} reset for tenant {args.tenant}")
        else:
            print(f"recompiled {await _recompile(conn)} policies")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if "KREP_MIGRATION_DATABASE_URL" not in os.environ:
        print("KREP_MIGRATION_DATABASE_URL is not set", file=sys.stderr)
        return 2
    try:
        asyncio.run(_run(args))
    except PolicyError as exc:
        print(_error(exc), file=sys.stderr)
        return 1
    return 0
