import { toNextJsHandler } from "better-auth/next-js";

import { auth, authOrigin, platformIdentityAuth, withIdentityLock } from "@/lib/auth";
import { getLoginToken } from "@/lib/session";

const baseHandlers = toNextJsHandler(auth);
const ADMIN_PATH = "/api/auth/admin/";
const METHODS: Record<string, string> = {
  "list-users": "GET", "create-user": "POST", "ban-user": "POST",
  "unban-user": "POST", "set-user-password": "POST", "remove-user": "POST",
};

async function handle(request: Request) {
  const url = new URL(request.url);
  const method = request.method as "GET" | "POST";
  if (!url.pathname.startsWith(ADMIN_PATH)) return baseHandlers[method](request);
  const action = url.pathname.slice(ADMIN_PATH.length);
  if (METHODS[action] !== method) return new Response(null, { status: 404 });
  const site = request.headers.get("sec-fetch-site");
  const sentOrigin = request.headers.get("origin");
  if ((site && site !== "same-origin" && site !== "none") || (sentOrigin && sentOrigin !== authOrigin)
    || (method === "POST" && !site && !sentOrigin)) {
    return Response.json({ message: "cross-origin request refused" }, { status: 403 });
  }
  const token = await getLoginToken(request.headers);
  if (!token) return Response.json({ message: "unauthenticated" }, { status: 401 });
  const apiUrl = (process.env.KREP_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
  async function registry(path: string, init: RequestInit = {}) {
    return fetch(`${apiUrl}/v1${path}`, {
      ...init, cache: "no-store", redirect: "error",
      headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    });
  }
  try {
    const decision = await registry("/me");
    if (!decision.ok) return new Response(decision.body, { status: decision.status, headers: { "content-type": "application/json" } });
    const me = await decision.json();
    if (!me.is_platform_admin) return Response.json({ message: "platform admin required" }, { status: 403 });
    const body = method === "POST" ? await request.clone().json() : {};
    if (action === "create-user" && (body.role && body.role !== "user" || body.data?.role)) {
      return Response.json({ message: "Use the platform grant to manage administrators" }, { status: 422 });
    }
    const userId = encodeURIComponent(String(body.userId ?? ""));
    if (action === "ban-user" && body.userId === me.user_id) {
      return Response.json({ message: "You cannot ban yourself" }, { status: 422 });
    }
    async function mutate() {
      if (action === "remove-user") {
        const state = await registry(`/admin/users/${userId}`);
        if (!state.ok) return new Response(state.body, { status: state.status });
        if (!(await state.json()).is_orphan) return Response.json({ message: "Only orphan accounts can be deleted" }, { status: 409 });
      }
      const event = { "create-user": "create", "remove-user": "delete", "set-user-password": "password_reset" }[action];
      const operationId = crypto.randomUUID();
      const auditTarget = action === "create-user" ? String(body.data?.username ?? body.email) : String(body.userId);
      async function record(target: string, action: string) {
        return registry(`/admin/users/${encodeURIComponent(target)}/identity-audit`, {
          method: "POST", body: JSON.stringify({ action, operation_id: operationId }),
        });
      }
      if (event) {
        const intent = await record(auditTarget, `${event}_requested`);
        if (!intent.ok) return Response.json({ message: "Audit unavailable; identity was not changed." }, { status: 502 });
      }
      if (action === "ban-user") {
        const disabled = await registry(`/admin/users/${userId}/disable`, { method: "POST", body: "{}" });
        if (!disabled.ok) return new Response(disabled.body, { status: disabled.status });
      }
      const handlers = toNextJsHandler(platformIdentityAuth(me.user_id));
      const result = await handlers[method](request);
      if (result.ok && action === "unban-user") {
        const enabled = await registry(`/admin/users/${userId}/enable`, { method: "POST" });
        if (!enabled.ok) return Response.json({ message: "Identity updated; registry update failed. Retry Unban to restore registry access." }, { status: 502 });
      }
      if (result.ok && event) {
        const target = action === "create-user" ? (await result.clone().json()).user.id : String(body.userId);
        const recorded = await record(target, event).catch(() => null);
        if (!recorded?.ok) return Response.json({ message: "Identity update succeeded and its request is audited; completion audit failed. Check the audit log before any further action." }, { status: 502 });
      }
      return result;
    }
    return action === "remove-user" ? await withIdentityLock(String(body.userId), mutate) : await mutate();
  } catch {
    return Response.json({ message: "Identity service unavailable. Retry this action." }, { status: 502 });
  }
}

export { handle as GET, handle as POST };
