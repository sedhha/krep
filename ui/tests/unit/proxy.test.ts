import { describe, expect, it, vi } from "vitest";

import { createProxy } from "../../src/lib/proxy";

const ORIGIN = "http://localhost:3000";
const UPSTREAM = "http://api.internal:8000";

function setup(
  options: {
    token?: string | null;
    upstream?: (req: Request) => Response | Promise<Response>;
  } = {},
) {
  const calls: Request[] = [];
  const upstream =
    options.upstream ??
    (() => Response.json({ ok: true }, { status: 200 }));
  const fetchMock = vi.fn(async (input: Request | string | URL, init?: RequestInit) => {
    const req = new Request(input, init);
    calls.push(req);
    return upstream(req);
  });
  const getToken = vi.fn(async () =>
    options.token === undefined ? "login.jwt.token" : options.token,
  );
  const proxy = createProxy({
    upstreamUrl: UPSTREAM,
    getToken,
    fetch: fetchMock as unknown as typeof fetch,
  });
  return { proxy, calls, getToken, fetchMock };
}

function request(path: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  if (!headers.has("origin") && !headers.has("sec-fetch-site")) {
    headers.set("origin", ORIGIN);
  }
  return new Request(`${ORIGIN}${path}`, { ...init, headers });
}

describe("session", () => {
  it("rejects without a session and never calls upstream", async () => {
    const { proxy, fetchMock } = setup({ token: null });
    const res = await proxy(request("/api/v1/me"));
    expect(res.status).toBe(401);
    expect(await res.json()).toEqual({
      error: "unauthenticated",
      message: "invalid or missing credentials",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards the login JWT as the bearer token", async () => {
    const { proxy, calls } = setup();
    await proxy(request("/api/v1/me"));
    expect(calls[0]?.headers.get("authorization")).toBe("Bearer login.jwt.token");
  });
});

describe("header handling", () => {
  it("drops client Authorization and Cookie", async () => {
    const { proxy, calls } = setup();
    await proxy(
      request("/api/v1/me", {
        headers: {
          authorization: "Bearer attacker",
          cookie: "better-auth.session_token=secret",
          "x-platform-key": "k".repeat(40),
        },
      }),
    );
    const sent = calls[0]!;
    expect(sent.headers.get("authorization")).toBe("Bearer login.jwt.token");
    expect(sent.headers.get("cookie")).toBeNull();
    expect(sent.headers.get("x-platform-key")).toBeNull();
  });

  it("forwards X-Org and X-Product", async () => {
    const { proxy, calls } = setup();
    await proxy(
      request("/api/v1/agents", {
        headers: { "x-org": "acme", "x-product": "billing-bot" },
      }),
    );
    expect(calls[0]?.headers.get("x-org")).toBe("acme");
    expect(calls[0]?.headers.get("x-product")).toBe("billing-bot");
  });

  it("omits selector headers that the client did not send", async () => {
    const { proxy, calls } = setup();
    await proxy(request("/api/v1/me"));
    expect(calls[0]?.headers.get("x-org")).toBeNull();
    expect(calls[0]?.headers.get("x-product")).toBeNull();
  });

  it("does not pass upstream Set-Cookie back to the browser", async () => {
    const { proxy } = setup({
      upstream: () =>
        new Response("{}", { headers: { "set-cookie": "a=b", "content-type": "application/json" } }),
    });
    const res = await proxy(request("/api/v1/me"));
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("content-type")).toBe("application/json");
  });
});

describe("routing", () => {
  it("maps /api/v1/* to upstream /v1/* and keeps the query string", async () => {
    const { proxy, calls } = setup();
    await proxy(request("/api/v1/agents/a1/versions?limit=5&q=x%20y"));
    expect(calls[0]?.url).toBe(`${UPSTREAM}/v1/agents/a1/versions?limit=5&q=x%20y`);
  });

  it.each([
    "/api/v1/../admin",
    "/api/v1/%2e%2e/admin",
    "/api/v1/a/%2E%2E/%2e%2e/admin",
    "/api/v1/%2e%2e/%2e%2e/admin",
  ])("never reaches outside /v1 for %s", async (path) => {
    const { proxy, calls } = setup();
    await proxy(request(path));
    for (const call of calls) {
      expect(new URL(call.url).pathname.startsWith("/v1/")).toBe(true);
    }
    expect(calls).toHaveLength(0);
  });

  it("refuses paths outside /api/v1", async () => {
    const { proxy, fetchMock } = setup();
    const res = await proxy(request("/api/other/me"));
    expect(res.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("responses", () => {
  it.each([
    [400, { error: "bad_request", message: "nope" }],
    [401, { error: "unauthenticated", message: "invalid or missing credentials" }],
    [404, { error: "not_found", message: "missing" }],
    [409, { error: "resource_in_use", message: "in use", blockers: [1] }],
    [422, { error: "link_scope_not_allowed", message: "no" }],
  ])("preserves status %i and the error body", async (status, body) => {
    const { proxy } = setup({ upstream: () => Response.json(body, { status }) });
    const res = await proxy(request("/api/v1/agents"));
    expect(res.status).toBe(status);
    expect(await res.json()).toEqual(body);
  });

  it("returns 502 when upstream is unreachable", async () => {
    const { proxy } = setup({
      upstream: () => {
        throw new TypeError("fetch failed");
      },
    });
    const res = await proxy(request("/api/v1/me"));
    expect(res.status).toBe(502);
    expect(((await res.json()) as { error: string }).error).toBe("upstream_unavailable");
  });
});

describe("request bodies", () => {
  it("streams a multipart body with its content type", async () => {
    const form = new FormData();
    form.set("file", new Blob(["hello"], { type: "text/plain" }), "a.txt");
    let received: { type: string | null; text: string } | undefined;
    const { proxy } = setup({
      upstream: async (req) => {
        received = {
          type: req.headers.get("content-type"),
          text: await req.text(),
        };
        return Response.json({ ok: true });
      },
    });
    const res = await proxy(request("/api/v1/agents", { method: "POST", body: form }));
    expect(res.status).toBe(200);
    expect(received?.type).toMatch(/^multipart\/form-data; boundary=/);
    expect(received?.text).toContain("hello");
  });

  it("forwards JSON bodies on write methods", async () => {
    let seen = "";
    const { proxy } = setup({
      upstream: async (req) => {
        seen = await req.text();
        return Response.json({});
      },
    });
    await proxy(
      request("/api/v1/products", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ slug: "p" }),
      }),
    );
    expect(seen).toBe('{"slug":"p"}');
  });
});

describe("same-origin", () => {
  it("refuses a foreign Origin", async () => {
    const { proxy, fetchMock } = setup();
    const res = await proxy(
      request("/api/v1/me", { headers: { origin: "http://evil.example" } }),
    );
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses Sec-Fetch-Site cross-site and same-site", async () => {
    const { proxy, fetchMock } = setup();
    for (const site of ["cross-site", "same-site"]) {
      const res = await proxy(
        request("/api/v1/me", { headers: { "sec-fetch-site": site } }),
      );
      expect(res.status).toBe(403);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts Sec-Fetch-Site same-origin without an Origin header", async () => {
    const { proxy } = setup();
    const res = await proxy(
      request("/api/v1/me", { headers: { "sec-fetch-site": "same-origin" } }),
    );
    expect(res.status).toBe(200);
  });

  it("refuses an unsafe method that carries neither Origin nor Sec-Fetch-Site", async () => {
    const { proxy, fetchMock } = setup();
    const res = await proxy(
      new Request(`${ORIGIN}/api/v1/products`, { method: "POST", body: "{}" }),
    );
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("checks origin before the session", async () => {
    const { proxy, getToken } = setup();
    await proxy(request("/api/v1/me", { headers: { origin: "http://evil.example" } }));
    expect(getToken).not.toHaveBeenCalled();
  });
});
