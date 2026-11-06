import { randomBytes } from "node:crypto";

import {
  type APIRequestContext,
  expect,
  type Page,
  type PlaywrightWorkerArgs,
  request,
  test,
} from "@playwright/test";
import { exportJWK, generateKeyPair, SignJWT } from "jose";

import { banUser } from "../../src/lib/ban";
import { API_URL, PLATFORM_KEY, UI_URL } from "./constants";

const PASSWORD = "correct-horse-battery";

function newUiApi(playwright: PlaywrightWorkerArgs["playwright"]) {
  const ip = `10.${randomBytes(1)[0]}.${randomBytes(1)[0]}.${randomBytes(1)[0]}`;
  return playwright.request.newContext({
    baseURL: UI_URL,
    extraHTTPHeaders: { "x-forwarded-for": ip },
  });
}

function uniqueName(prefix: string): string {
  return `${prefix}${randomBytes(4).toString("hex")}`;
}

async function signUpApi(api: APIRequestContext, username: string): Promise<string> {
  const res = await api.post("/api/auth/sign-up/email", {
    headers: { origin: UI_URL },
    data: { username, name: username, email: `${username}@example.test`, password: PASSWORD },
  });
  expect({ status: res.status(), body: await res.text() }).toMatchObject({ status: 200 });
  return ((await res.json()) as { user: { id: string } }).user.id;
}

async function signInApi(api: APIRequestContext, username: string): Promise<void> {
  const res = await api.post("/api/auth/sign-in/username", {
    headers: { origin: UI_URL },
    data: { username, password: PASSWORD },
  });
  expect(res.ok()).toBeTruthy();
}

async function loginJwt(api: APIRequestContext): Promise<string> {
  const res = await api.get("/api/auth/token");
  expect(res.ok()).toBeTruthy();
  return ((await res.json()) as { token: string }).token;
}

async function fastapiMe(token: string): Promise<{ status: number; body: unknown }> {
  const api = await request.newContext();
  const res = await api.get(`${API_URL}/v1/me`, {
    headers: { authorization: `Bearer ${token}` },
  });
  const out = { status: res.status(), body: await res.json() };
  await api.dispose();
  return out;
}

async function proxiedMe(page: Page): Promise<{ status: number; body: unknown }> {
  return page.evaluate(async () => {
    const res = await fetch("/api/v1/me");
    return { status: res.status, body: await res.json() };
  });
}

test("sign up, username sign-in and proxied /v1/me", async ({ page, browser }) => {
  const username = uniqueName("alice");

  await page.goto("/signup");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Email").fill(`${username}@example.test`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).not.toHaveURL(/\/signup$/);

  const fresh = await browser.newContext();
  const login = await fresh.newPage();
  await login.goto("/login");
  await login.getByLabel("Username").fill(username);
  await login.getByLabel("Password").fill(PASSWORD);
  await login.getByRole("button", { name: "Sign in" }).click();
  await expect(login).not.toHaveURL(/\/login$/);

  const me = await proxiedMe(login);
  expect(me.status).toBe(200);
  expect(me.body).toMatchObject({
    username,
    is_platform_admin: false,
    memberships: [],
  });
  await fresh.close();
});

test("proxy requires a session", async () => {
  const anonymous = await request.newContext({ baseURL: UI_URL });
  const res = await anonymous.get("/api/v1/me");
  expect(res.status()).toBe(401);
  await anonymous.dispose();
});

test("FastAPI accepts the login JWT and rejects other issuers", async ({ playwright }) => {
  const username = uniqueName("bob");
  const api = await newUiApi(playwright);
  const id = await signUpApi(api, username);
  await signInApi(api, username);
  const token = await loginJwt(api);

  const ok = await fastapiMe(token);
  expect(ok.status).toBe(200);
  expect(ok.body).toMatchObject({ user_id: id, username });

  const { privateKey, publicKey } = await generateKeyPair("ES256");
  const kid = (await exportJWK(publicKey)).x ?? "other";
  const forged = async (claims: { iss: string; aud: string }) =>
    new SignJWT({ username })
      .setProtectedHeader({ alg: "ES256", kid })
      .setSubject(id)
      .setIssuer(claims.iss)
      .setAudience(claims.aud)
      .setExpirationTime("1h")
      .sign(privateKey);

  const otherIssuer = await fastapiMe(await forged({ iss: "https://evil.example", aud: "krep" }));
  const unknownKey = await fastapiMe(await forged({ iss: UI_URL, aud: "krep" }));
  for (const rejected of [otherIssuer, unknownKey]) {
    expect(rejected.status).toBe(401);
    expect(rejected.body).toEqual({
      error: "unauthenticated",
      message: "invalid or missing credentials",
    });
  }
  await api.dispose();
});

test("ban pairing makes the next request 401 despite an unexpired JWT", async ({ playwright }) => {
  const adminName = uniqueName("admin");
  const victimName = uniqueName("victim");

  const adminApi = await newUiApi(playwright);
  const adminId = await signUpApi(adminApi, adminName);
  const granted = await adminApi.put(`${API_URL}/v1/admin/platform-admins/${adminId}`, {
    headers: { "x-platform-key": PLATFORM_KEY },
  });
  expect(granted.ok()).toBeTruthy();
  await signInApi(adminApi, adminName);

  const victimApi = await newUiApi(playwright);
  const victimId = await signUpApi(victimApi, victimName);
  await signInApi(victimApi, victimName);
  const token = await loginJwt(victimApi);
  expect((await fastapiMe(token)).status).toBe(200);

  const deps = {
    ban: async (userId: string) => {
      const res = await adminApi.post("/api/auth/admin/ban-user", {
        headers: { origin: UI_URL },
        data: { userId, banReason: "e2e" },
      });
      if (!res.ok()) throw new Error(`ban failed: ${res.status()}`);
    },
    disable: async (userId: string) => {
      const api = await request.newContext();
      const res = await api.post(`${API_URL}/v1/admin/users/${userId}/disable`, {
        headers: { "x-platform-key": PLATFORM_KEY },
        data: { reason: "e2e" },
      });
      await api.dispose();
      if (!res.ok()) throw new Error(`disable failed: ${res.status()}`);
    },
  };

  await banUser(victimId, deps);
  await banUser(victimId, deps);

  const after = await fastapiMe(token);
  expect(after.status).toBe(401);
  expect(after.body).toEqual({
    error: "unauthenticated",
    message: "invalid or missing credentials",
  });
  expect((await victimApi.get("/api/v1/me")).status()).toBe(401);

  await adminApi.dispose();
  await victimApi.dispose();
});

test("password fields clear after failed login and sign-up submissions", async ({ page, playwright }) => {
  const name = uniqueName("passwordclear");
  const api = await newUiApi(playwright);
  await signUpApi(api, name);
  await page.setExtraHTTPHeaders({ "x-forwarded-for": `10.50.${randomBytes(1)[0]}.${randomBytes(1)[0]}` });
  await page.goto("/login");
  await page.getByLabel("Username").fill(name);
  await page.getByLabel("Password").fill("wrong-password-value");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Invalid username or password" })).toBeVisible();
  await expect(page.getByLabel("Password")).toHaveValue("");
  await page.goto("/signup");
  await page.getByLabel("Username").fill(name);
  await page.getByLabel("Email").fill(`${name}@example.test`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByLabel("Password")).toHaveValue("");
  await api.dispose();
});
