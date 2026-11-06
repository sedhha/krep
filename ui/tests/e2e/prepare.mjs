import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import pg from "pg";

const env = process.env;
const database = env.KREP_E2E_DATABASE;
const host = env.KREP_E2E_DB_HOST;
const ui = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const root = resolve(ui, "..");

function run(command, args, cwd) {
  const result = spawnSync(command, args, { cwd, env, stdio: "inherit" });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const admin = new pg.Client({ connectionString: env.KREP_E2E_ADMIN_DATABASE_URL });
await admin.connect();
await admin.query(`DROP DATABASE IF EXISTS ${database} WITH (FORCE)`);
await admin.query(`CREATE DATABASE ${database} OWNER krep_owner`);
await admin.end();

const db = new pg.Client({
  connectionString: `postgresql://postgres:dev@${host}/${database}`,
});
await db.connect();
for (const statement of [
  "CREATE EXTENSION IF NOT EXISTS pg_trgm",
  "CREATE EXTENSION IF NOT EXISTS pgcrypto",
  "ALTER SCHEMA public OWNER TO krep_owner",
  "GRANT USAGE ON SCHEMA public TO krep_app, krep_platform",
  "CREATE SCHEMA auth AUTHORIZATION krep_auth",
  "GRANT USAGE ON SCHEMA auth TO krep_owner",
  "ALTER DEFAULT PRIVILEGES FOR ROLE krep_auth IN SCHEMA auth GRANT SELECT ON TABLES TO krep_owner WITH GRANT OPTION",
]) {
  await db.query(statement);
}
await db.end();

run("pnpm", ["dlx", "auth@1.7.15", "migrate", "--config", "src/lib/auth.ts", "-y"], ui);
run("uv", ["run", "alembic", "upgrade", "head"], root);
