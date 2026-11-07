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

export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  format?: string;
  writeOnly?: boolean;
  default?: unknown;
  enum?: string[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
}

export interface AuthAdapter {
  type: string;
  config_schema: JsonSchema;
  secret_fields: string[];
}

export interface Organization {
  id: string;
  slug: string;
  name: string;
  status: "active" | "suspended" | "pending_delete";
  is_platform: boolean;
  legal_hold: boolean;
  delete_after: string | null;
}

export interface Member {
  user_id: string;
  username: string | null;
  email: string | null;
  groups: string[];
}

export interface AuthConfig {
  adapter: string;
  config: Record<string, unknown>;
  secret_set: boolean;
}

export interface AuditRow {
  id: number;
  actor: string;
  action: string;
  tenant_id: string | null;
  target: string | null;
  detail: Record<string, unknown> | null;
  at: string;
}

export interface OrganizationInput {
  slug: string;
  name: string;
  admin_user: string;
  capabilities: Record<string, string>;
  auth?: { adapter: string; config: Record<string, unknown>; secret?: string };
}

const segment = encodeURIComponent;
export const adminApi = {
  organizations: () => api<{ items: Organization[] }>("/admin/organizations"),
  organization: (id: string) => api<Organization>(`/admin/organizations/${segment(id)}`),
  adapters: () => api<{ items: AuthAdapter[] }>("/admin/auth-adapters"),
  createOrganization: (json: OrganizationInput) => api<Organization>("/admin/organizations", { method: "POST", json }),
  lifecycle: (id: string, action: string, json?: unknown) => api<Organization>(`/admin/organizations/${segment(id)}/${action}`, { method: "POST", json }),
  legalHold: (id: string, legal_hold: boolean) => api<Organization>(`/admin/organizations/${segment(id)}/legal-hold`, { method: "PUT", json: { legal_hold } }),
  members: (id: string) => api<{ items: Member[] }>(`/admin/organizations/${segment(id)}/members`),
  auth: (id: string) => api<AuthConfig>(`/admin/organizations/${segment(id)}/auth`),
  blockers: (id: string) => api<{ legal_hold: boolean; items: { resource: string; organization: string; kind: string; referrers: number }[] }>(`/admin/organizations/${segment(id)}/purge-blockers`),
  userStatus: (id: string) => api<{ user_id: string; is_platform_admin: boolean; memberships: string[]; is_orphan: boolean; disabled: boolean }>(`/admin/users/${segment(id)}`),
  attach: (id: string, user: string, groups: string[]) => api<Member>(`/admin/organizations/${segment(id)}/members/${segment(user)}`, { method: "PUT", json: { groups } }),
  detach: (id: string, user: string) => api<void>(`/admin/organizations/${segment(id)}/members/${segment(user)}`, { method: "DELETE" }),
  grant: (user: string) => api(`/admin/platform-admins/${segment(user)}`, { method: "PUT" }),
  revoke: (user: string) => api<void>(`/admin/platform-admins/${segment(user)}`, { method: "DELETE" }),
  disable: (user: string) => api(`/admin/users/${segment(user)}/disable`, { method: "POST", json: {} }),
  enable: (user: string) => api(`/admin/users/${segment(user)}/enable`, { method: "POST" }),
  audit: (before?: number, limit = 100) => api<{ items: AuditRow[] }>(`/admin/audit?limit=${limit}${before ? `&before=${before}` : ""}`),
};

export interface IdentityUser {
  id: string;
  username?: string;
  name: string;
  email: string;
  banned?: boolean;
}

export async function identityApi<T>(action: string, json?: unknown, query = ""): Promise<T> {
  const response = await fetch(`/api/auth/admin/${action}${query}`, {
    method: json === undefined ? "GET" : "POST",
    headers: json === undefined ? undefined : { "content-type": "application/json" },
    body: json === undefined ? undefined : JSON.stringify(json),
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message ?? "Identity request failed");
  return payload as T;
}
