import { randomBytes } from "node:crypto";

import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import { API_URL, PLATFORM_KEY, UI_URL } from "./constants";

const PASSWORD = "correct-horse-battery";
const unique = (prefix: string) => `${prefix}${randomBytes(4).toString("hex")}`;

async function signup(api: APIRequestContext, username: string) {
  const res = await api.post(`${UI_URL}/api/auth/sign-up/email`, {
    headers: { origin: UI_URL, "x-forwarded-for": `10.20.${randomBytes(1)[0]}.${randomBytes(1)[0]}` },
    data: { username, name: username, email: `${username}@example.test`, password: PASSWORD },
  });
  expect(res.status()).toBe(200);
  return (await res.json()).user.id as string;
}

async function login(page: Page, username: string) {
  await page.setExtraHTTPHeaders({ "x-forwarded-for": `10.30.${randomBytes(1)[0]}.${randomBytes(1)[0]}` });
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(`${UI_URL}/`);
}

async function createAdmin(page: Page, api: APIRequestContext) {
  const name = unique("platform");
  const id = await signup(api, name);
  const res = await api.put(`${API_URL}/v1/admin/platform-admins/${id}`, {
    headers: { "x-platform-key": PLATFORM_KEY },
  });
  expect(res.status()).toBe(200);
  await login(page, name);
  return { id, name };
}

async function confirm(page: Page, action: string) {
  await page.getByRole("button", { name: action, exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}

test("v2ac6 non-admin cannot open platform pages or use platform APIs", async ({ page, request }) => {
  const name = unique("ordinary");
  await signup(request, name);
  await login(page, name);
  await page.goto("/platform/organizations");
  await expect(page.getByRole("heading", { name: "Platform access required" })).toBeVisible();
  const status = await page.evaluate(async () => (await fetch("/api/v1/admin/organizations")).status);
  expect(status).toBe(403);
  await expect(page.getByRole("link", { name: "New organisation" })).toHaveCount(0);
});

test("v2ac19 platform admin onboards an organisation and v2ac16 manages its lifecycle", async ({ page, request, browser }) => {
  await createAdmin(page, request);
  const ownerName = unique("owner");
  await signup(request, ownerName);
  const slug = unique("tenant");
  const secret = unique("private-secret-0123456789abcdef-");
  const responses: string[] = [];
  page.on("response", async (response) => {
    if (response.url().includes("/api/v1/")) responses.push(await response.text().catch(() => ""));
  });
  await page.goto("/platform/organizations");
  await page.getByRole("link", { name: "New organisation" }).click();
  await page.getByLabel("Slug", { exact: true }).fill(slug);
  await page.getByLabel("Name", { exact: true }).fill("Walkthrough tenant");
  await page.getByLabel("First admin username").fill(ownerName);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("Authentication adapter").selectOption("hmac");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByLabel("Secret", { exact: true }).fill(secret);
  await page.getByLabel("Audience", { exact: true }).fill("krep");
  await page.getByRole("button", { name: "Create organisation", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Walkthrough tenant" })).toBeVisible();
  await expect(page.getByText("Secret configured: yes")).toBeVisible();
  expect(await page.content()).not.toContain(secret);
  expect(responses.join("")).not.toContain(secret);
  await expect(page.getByText(ownerName, { exact: true })).toBeVisible();
  const readerName = unique("reader");
  const readerId = await signup(request, readerName);
  await page.getByLabel("User ID", { exact: true }).fill(readerId);
  await page.getByLabel("Groups (comma separated)").fill("reader");
  await page.getByRole("button", { name: "Save membership" }).click();
  await expect(page.getByText(readerName, { exact: true })).toBeVisible();
  await page.getByLabel("User ID", { exact: true }).fill(readerId);
  await page.getByLabel("Groups (comma separated)").fill("writer");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Save membership" }).click();
  await expect(page.getByRole("row").filter({ hasText: readerName }).getByText("writer", { exact: true })).toBeVisible();
  await confirm(page, `Detach ${readerName}`);
  await expect(page.getByText(readerName, { exact: true })).toHaveCount(0);

  const context = await browser.newContext();
  const owner = await context.newPage();
  await login(owner, ownerName);
  const selectedStatus = () => owner.evaluate(async (org) => (await fetch("/api/v1/me", { headers: { "x-org": org } })).status, slug);
  expect(await selectedStatus()).toBe(200);
  await confirm(page, "Suspend");
  await expect(page.getByText("Status: suspended", { exact: true })).toBeVisible();
  expect(await selectedStatus()).toBe(401);
  await expect(page.getByText("org.suspend", { exact: true })).toBeVisible();
  await confirm(page, "Activate");
  await expect(page.getByText("Status: active", { exact: true })).toBeVisible();
  expect(await selectedStatus()).toBe(200);
  await page.getByLabel("Grace days").fill("1");
  await confirm(page, "Schedule delete");
  await expect(page.getByText("Status: pending_delete", { exact: true })).toBeVisible();
  await expect(page.getByText(/Delete after:/)).toBeVisible();
  await confirm(page, "Enable legal hold");
  await expect(page.getByText("Purge blocked by legal hold", { exact: true })).toBeVisible();
  await confirm(page, "Cancel delete");
  await expect(page.getByText("Status: suspended", { exact: true })).toBeVisible();
  await page.screenshot({ path: "/tmp/krep-platform-organization.png", fullPage: true });
  await context.close();
});

test("v2ac6 platform grant enables identity administration and revocation removes it", async ({ page, request, browser }) => {
  await createAdmin(page, request);
  const target = unique("managed");
  const targetId = await signup(request, target);
  const disabled = await request.post(`${API_URL}/v1/admin/users/${targetId}/disable`, { headers: { "x-platform-key": PLATFORM_KEY }, data: {} });
  expect(disabled.status()).toBe(200);
  await page.goto("/platform/users");
  await expect(page.getByRole("heading", { name: "Users", exact: true })).toBeVisible();
  const row = page.getByRole("table", { name: "Accounts" }).getByRole("row").filter({ has: page.getByText(target, { exact: true }) });
  await expect(row).toBeVisible();
  await expect(row.getByText(/Registry disabled/)).toBeVisible();
  await row.getByRole("button", { name: "Unban", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await row.getByRole("button", { name: "Ban", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(row.getByText("Banned", { exact: true })).toBeVisible();
  await expect(page.getByText("user.disable", { exact: true }).first()).toBeVisible();
  await row.getByRole("button", { name: "Unban", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(row.getByText("Active", { exact: true })).toBeVisible();
  await row.getByRole("button", { name: "Grant platform admin", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(row.getByRole("button", { name: "Revoke platform admin", exact: true })).toBeVisible();
  const targetContext = await browser.newContext();
  const targetPage = await targetContext.newPage();
  await login(targetPage, target);
  expect(await targetPage.evaluate(async () => (await fetch("/api/auth/admin/list-users")).status)).toBe(200);
  await row.getByRole("button", { name: "Revoke platform admin", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(row.getByRole("button", { name: "Delete orphan", exact: true })).toBeEnabled();
  expect(await targetPage.evaluate(async () => (await fetch("/api/auth/admin/list-users")).status)).toBe(403);
  await targetContext.close();
  await row.getByRole("button", { name: "Delete orphan", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirm", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(row).toHaveCount(0);
  const deleted = await request.get(`${API_URL}/v1/admin/users/${targetId}`, { headers: { "x-platform-key": PLATFORM_KEY } });
  expect(deleted.status()).toBe(404);
});


test("v2ac6 platform admin creates users and resets passwords without exposing either password", async ({ page, request, browser }) => {
  await createAdmin(page, request);
  await page.goto("/platform/users");
  const name = unique("created");
  await page.getByLabel("Username", { exact: true }).fill(name);
  await page.getByLabel("Email", { exact: true }).fill(`${name}@example.test`);
  await page.getByLabel("Initial password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create user", exact: true }).click();
  const row = page.getByRole("table", { name: "Accounts" }).getByRole("row").filter({ has: page.getByText(name, { exact: true }) });
  await expect(row).toBeVisible();
  expect(await page.getByLabel("Initial password").inputValue()).toBe("");
  await expect(page.getByText("user.create", { exact: true }).first()).toBeVisible();
  await row.getByLabel(`New password for ${name}`).fill("changed-correct-horse-battery");
  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: "Reset password", exact: true }).click();
  await expect(page.getByText("user.password_reset", { exact: true }).first()).toBeVisible();
  expect(await row.getByLabel(`New password for ${name}`).inputValue()).toBe("");
  const fresh = await browser.newContext();
  const loginResult = await fresh.request.post(`${UI_URL}/api/auth/sign-in/username`, {
    headers: { origin: UI_URL, "x-forwarded-for": `10.40.${randomBytes(1)[0]}.${randomBytes(1)[0]}` },
    data: { username: name, password: "changed-correct-horse-battery" },
  });
  expect(loginResult.status()).toBe(200);
  await fresh.close();
});
