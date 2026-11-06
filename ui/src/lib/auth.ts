import { betterAuth } from "better-auth";
import { admin, jwt, username } from "better-auth/plugins";
import { Pool } from "pg";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
}

const baseURL = required("BETTER_AUTH_URL");
const ttlSeconds = Number(process.env.KREP_LOGIN_JWT_TTL_SECONDS || 3600);

const pool = new Pool({
  connectionString: required("KREP_AUTH_DATABASE_URL"),
  options: "-c search_path=auth",
});

export const signupAllowed = ["1", "true", "yes"].includes(
  (process.env.KREP_ALLOW_SIGNUP ?? "").toLowerCase(),
);

export const auth = betterAuth({
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
    admin(),
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
