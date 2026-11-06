export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly error: string,
    message: string,
    readonly detail: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export interface Membership {
  organization: string;
  groups: string[];
}

export interface Me {
  user_id: string;
  username: string;
  is_platform_admin: boolean;
  memberships: Membership[];
  resolved: {
    organization: string;
    product: string | null;
    can_read: boolean;
    can_write: boolean;
    can_admin: boolean;
  } | null;
}

export interface Scope {
  org?: string;
  product?: string;
}

export interface RequestOptions {
  method?: string;
  scope?: Scope;
  json?: unknown;
  body?: BodyInit;
  signal?: AbortSignal;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers();
  if (options.scope?.org) headers.set("x-org", options.scope.org);
  if (options.scope?.product) headers.set("x-product", options.scope.product);
  let body = options.body;
  if (options.json !== undefined) {
    headers.set("content-type", "application/json");
    body = JSON.stringify(options.json);
  }
  const res = await fetch(`/api/v1${path}`, {
    method: options.method ?? "GET",
    headers,
    body,
    signal: options.signal,
  });
  if (res.status === 204) return undefined as T;
  const payload: unknown = await res.json().catch(() => ({}));
  if (!res.ok) {
    const { error, message, ...detail } = payload as Record<string, unknown>;
    throw new ApiError(res.status, String(error ?? "error"), String(message ?? res.statusText), detail);
  }
  return payload as T;
}

export const getMe = (scope?: Scope) => api<Me>("/me", { scope });
