import { betterAuth } from "better-auth";
import { admin, jwt, username } from "better-auth/plugins";
import { Client, Pool } from "pg";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

const baseURL = required("BETTER_AUTH_URL");
export const authOrigin = new URL(baseURL).origin;
const ttlSeconds = Number(process.env.KREP_LOGIN_JWT_TTL_SECONDS || 3600);

const pool = new Pool({
  connectionString: required("KREP_AUTH_DATABASE_URL"),
  options: "-c search_path=auth",
});

export const signupAllowed = ["1", "true", "yes"].includes(
  (process.env.KREP_ALLOW_SIGNUP ?? "").toLowerCase(),
);

function createAuth(adminUserIds: string[] = []) {
  return betterAuth({
  baseURL,
  secret: required("BETTER_AUTH_SECRET"),
  trustedOrigins: [baseURL],
  database: pool,
  emailAndPassword: {
    enabled: true,
    requireEmailVerification: false,
    disableSignUp: !signupAllowed,
  },
  rateLimit: { enabled: true },
  plugins: [
    username(),
    admin({ adminUserIds }),
    jwt({
      jwt: {
        issuer: required("KREP_LOGIN_ISSUER"),
        audience: required("KREP_LOGIN_AUDIENCE"),
        expirationTime: `${ttlSeconds}s`,
        definePayload: ({ user }) => ({ username: user.username }),
      },
    }),
  ],
  });
}

export const auth = createAuth();

export const platformIdentityAuth = (userId: string) => createAuth([userId]);

export async function withIdentityLock<T>(userId: string, operation: () => Promise<T>): Promise<T> {
  const connection = new Client({ connectionString: required("KREP_AUTH_DATABASE_URL") });
  await connection.connect();
  try {
    await connection.query("BEGIN");
    await connection.query("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", [userId]);
    const result = await operation();
    await connection.query("COMMIT");
    return result;
  } catch (error) {
    await connection.query("ROLLBACK");
    throw error;
  } finally {
    await connection.end();
  }
}
