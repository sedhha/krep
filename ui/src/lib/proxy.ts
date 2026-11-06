const PREFIX = "/api/v1/";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const FORWARD_REQUEST_HEADERS = [
  "accept",
  "content-type",
  "if-none-match",
  "x-org",
  "x-product",
];
const FORWARD_RESPONSE_HEADERS = [
  "cache-control",
  "content-disposition",
  "content-type",
  "etag",
];

export interface ProxyDeps {
  upstreamUrl: string;
  getToken: (headers: Headers) => Promise<string | null>;
  fetch?: typeof fetch;
}

function errorResponse(status: number, error: string, message: string) {
  return Response.json({ error, message }, { status });
}

function isSameOrigin(req: Request, origin: string): boolean {
  const fetchSite = req.headers.get("sec-fetch-site");
  if (fetchSite !== null) {
    return fetchSite === "same-origin" || fetchSite === "none";
  }
  const sent = req.headers.get("origin");
  if (sent !== null) {
    return sent === origin;
  }
  return SAFE_METHODS.has(req.method);
}

export function createProxy({ upstreamUrl, getToken, fetch: doFetch = fetch }: ProxyDeps) {
  const base = upstreamUrl.replace(/\/+$/, "");

  return async function proxy(req: Request): Promise<Response> {
    const url = new URL(req.url);

    if (!isSameOrigin(req, url.origin)) {
      return errorResponse(403, "forbidden", "cross-origin request refused");
    }
    if (!url.pathname.startsWith(PREFIX)) {
      return errorResponse(404, "not_found", "not found");
    }

    const token = await getToken(req.headers);
    if (token === null) {
      return errorResponse(401, "unauthenticated", "invalid or missing credentials");
    }

    const headers = new Headers();
    for (const name of FORWARD_REQUEST_HEADERS) {
      const value = req.headers.get(name);
      if (value !== null) headers.set(name, value);
    }
    headers.set("authorization", `Bearer ${token}`);

    const hasBody = !SAFE_METHODS.has(req.method) && req.body !== null;
    const target = `${base}/v1/${url.pathname.slice(PREFIX.length)}${url.search}`;

    let upstream: Response;
    try {
      upstream = await doFetch(target, {
        method: req.method,
        headers,
        body: hasBody ? req.body : undefined,
        redirect: "manual",
        ...(hasBody ? { duplex: "half" } : {}),
      } as RequestInit);
    } catch {
      return errorResponse(502, "upstream_unavailable", "upstream unavailable");
    }

    const out = new Headers();
    for (const name of FORWARD_RESPONSE_HEADERS) {
      const value = upstream.headers.get(name);
      if (value !== null) out.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: out });
  };
}
