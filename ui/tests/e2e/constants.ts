export const UI_PORT = 3100;
export const API_PORT = 8100;
export const UI_URL = `http://localhost:${UI_PORT}`;
export const API_URL = `http://localhost:${API_PORT}`;
export const PLATFORM_KEY = "e2e-platform-key-0123456789abcdef0123456789";
export const E2E_DATABASE = "krep_e2e";
export const DB_HOST = process.env.KREP_E2E_DB_HOST ?? "localhost:5432";

export function roleUrl(role: string, database = E2E_DATABASE): string {
  return `postgresql://${role}:dev@${DB_HOST}/${database}`;
}

export const stackEnv = {
  KREP_ENV: "local",
  KREP_E2E_DATABASE: E2E_DATABASE,
  KREP_E2E_ADMIN_DATABASE_URL: `postgresql://postgres:dev@${DB_HOST}/postgres`,
  KREP_E2E_DB_HOST: DB_HOST,
  KREP_DATABASE_URL: roleUrl("krep_app"),
  KREP_PLATFORM_DATABASE_URL: roleUrl("krep_platform"),
  KREP_MIGRATION_DATABASE_URL: roleUrl("krep_owner").replace(
    "postgresql://",
    "postgresql+psycopg://",
  ),
  KREP_AUTH_DATABASE_URL: roleUrl("krep_auth"),
  KREP_ENCRYPTION_KEYS: "k1:7ay3-HFquKi83dN5MGAMzTgYi5qv_1pYMv69wHIGFFQ=",
  KREP_PLATFORM_ADMIN_KEY: PLATFORM_KEY,
  KREP_LOGIN_ISSUER: UI_URL,
  KREP_LOGIN_JWKS_URL: `${UI_URL}/api/auth/jwks`,
  KREP_LOGIN_AUDIENCE: "krep",
  KREP_LOGIN_JWT_TTL_SECONDS: "3600",
  KREP_ALLOW_SIGNUP: "true",
  KREP_API_URL: API_URL,
  BETTER_AUTH_URL: UI_URL,
  BETTER_AUTH_SECRET: "e2e-better-auth-secret-0123456789abcdef0123456789",
};
