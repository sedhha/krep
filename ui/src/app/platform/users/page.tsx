"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { AuditPanel, ConfirmAction, ErrorMessage } from "@/components/ui/console";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { adminApi, identityApi, type IdentityUser } from "@/lib/api";

function UserRow({ user }: { user: IdentityUser }) {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["user-status", user.id], queryFn: () => adminApi.userStatus(user.id) });
  const blocked = user.banned || status.data?.disabled;
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  async function run(action: () => Promise<unknown>) {
    await action(); await client.invalidateQueries();
  }
  async function reset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!window.confirm("Reset this user’s password?")) return;
    const form = event.currentTarget;
    const password = String(new FormData(form).get("password"));
    form.reset(); setError(null); setPending(true);
    try { await run(() => identityApi("set-user-password", { userId: user.id, newPassword: password })); }
    catch (e) { setError(e); }
    finally { setPending(false); }
  }
  return <TableRow>
    <TableCell><span>{user.username ?? user.name}</span><small className="block">{user.email}</small><small>{user.id}</small></TableCell>
    <TableCell><span>{user.banned ? "Banned" : "Active"}</span><small className="block">{status.data?.disabled && "Registry disabled · "}{status.data?.is_platform_admin ? "Platform admin" : status.data?.is_orphan ? "Orphan account" : "Organisation member"}</small><ErrorMessage error={status.error} /></TableCell>
    <TableCell><div className="actions">
      <ConfirmAction label={blocked ? "Unban" : "Ban"} description={blocked ? "Restore sign-in and registry access?" : "Block sign-in and all registry requests immediately? Retry if either service reports a failure."} onConfirm={() => run(() => identityApi(blocked ? "unban-user" : "ban-user", { userId: user.id }))} />
      <ConfirmAction label={status.data?.is_platform_admin ? "Revoke platform admin" : "Grant platform admin"} disabled={!status.data}
        description={status.data?.is_platform_admin ? "Remove all platform administration permissions?" : "Allow this user to administer every organisation?"}
        onConfirm={() => run(() => status.data?.is_platform_admin ? adminApi.revoke(user.id) : adminApi.grant(user.id))} />
      <ConfirmAction label="Delete orphan" description="Permanently delete this orphan account and its identity data?" disabled={!status.data?.is_orphan} onConfirm={() => run(() => identityApi("remove-user", { userId: user.id }))} />
    </div>
      <form onSubmit={reset}><label>New password for {user.username ?? user.name}<Input name="password" type="password" autoComplete="new-password" minLength={8} required /></label>
        <small>Confirm the reset when prompted.</small><Button type="submit" variant="outline" disabled={pending}>Reset password</Button><ErrorMessage error={error} />
      </form>
    </TableCell>
  </TableRow>;
}

export default function UsersPage() {
  const client = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const users = useQuery({ queryKey: ["users", offset], queryFn: () => identityApi<{ users: IdentityUser[]; total: number }>("list-users", undefined, `?limit=25&offset=${offset}&sortBy=createdAt&sortDirection=desc`) });
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const password = String(data.get("password"));
    (form.elements.namedItem("password") as HTMLInputElement).value = "";
    setError(null); setPending(true);
    try {
      await identityApi("create-user", { email: String(data.get("email")), name: String(data.get("username")), password, data: { username: String(data.get("username")) } });
      form.reset(); setOffset(0); await client.invalidateQueries();
    } catch (e) { setError(e); }
    finally { setPending(false); }
  }
  return <><h1>Users</h1><section><h2>Create user</h2><form onSubmit={create}>
    <label>Username<Input name="username" required /></label><label>Email<Input name="email" type="email" required /></label><label>Initial password<Input name="password" type="password" autoComplete="new-password" minLength={8} required /></label>
    <Button type="submit" disabled={pending}>Create user</Button><ErrorMessage error={error} />
  </form></section>
    <section><h2>Accounts</h2><ErrorMessage error={users.error} />
      {users.isPending ? <p>Loading users…</p> : <Table aria-label="Accounts"><TableHeader><TableRow><TableHead>User</TableHead><TableHead>Status</TableHead><TableHead>Actions</TableHead></TableRow></TableHeader>
        <TableBody>{users.data?.users.map((user) => <UserRow key={user.id} user={user} />)}</TableBody></Table>}
      <div className="actions"><Button variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous users</Button><Button variant="outline" disabled={!users.data || offset + 25 >= users.data.total} onClick={() => setOffset(offset + 25)}>Next users</Button></div>
    </section><AuditPanel /></>;
}
