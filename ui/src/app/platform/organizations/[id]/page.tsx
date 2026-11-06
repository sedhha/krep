"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { AuditPanel, ConfirmAction, ErrorMessage } from "@/components/ui/console";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { adminApi, ApiError } from "@/lib/api";

export default function OrganizationPage() {
  const { id } = useParams<{ id: string }>();
  const client = useQueryClient();
  const org = useQuery({ queryKey: ["organization", id], queryFn: () => adminApi.organization(id) });
  const members = useQuery({ queryKey: ["members", id], queryFn: () => adminApi.members(id) });
  const auth = useQuery({ queryKey: ["org-auth", id], queryFn: () => adminApi.auth(id) });
  const blockers = useQuery({ queryKey: ["blockers", id], queryFn: () => adminApi.blockers(id) });
  const [days, setDays] = useState("30");
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  async function refresh(action: () => Promise<unknown>) {
    await action();
    await client.invalidateQueries();
  }
  async function attach(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    if (members.data?.items.some((member) => member.user_id === data.get("user_id")) && !window.confirm("Replace this member’s groups?")) return;
    setError(null); setPending(true);
    try {
      await refresh(() => adminApi.attach(id, String(data.get("user_id")), String(data.get("groups")).split(",").map((g) => g.trim()).filter(Boolean)));
      form.reset();
    } catch (e) { setError(e); }
    finally { setPending(false); }
  }
  if (!org.data) return <><h1>Organisation</h1>{org.isPending ? <p>Loading organisation…</p> : <ErrorMessage error={org.error} />}</>;
  const value = org.data;
  const noAuth = auth.error instanceof ApiError && auth.error.status === 404;
  return <><h1>{value.name}</h1>
    <section><h2>Organisation details</h2><p>Slug: {value.slug}</p><p>Status: {value.status}</p>
      {value.delete_after && <p>Delete after: {new Date(value.delete_after).toLocaleString()}</p>}
      <p>Legal hold: {value.legal_hold ? "yes" : "no"}</p>
      <div className="actions">
        {value.status === "active" && !value.is_platform && <ConfirmAction label="Suspend" description="Block all requests for this organisation immediately? Data will be retained." onConfirm={() => refresh(() => adminApi.lifecycle(id, "suspend"))} />}
        {value.status === "suspended" && <ConfirmAction label="Activate" description="Restore access to this organisation?" onConfirm={() => refresh(() => adminApi.lifecycle(id, "activate"))} />}
        <ConfirmAction label={value.legal_hold ? "Clear legal hold" : "Enable legal hold"} description={value.legal_hold ? "Allow scheduled purge after other blockers are cleared?" : "Prevent purge until this legal hold is cleared?"} onConfirm={() => refresh(() => adminApi.legalHold(id, !value.legal_hold))} />
      </div>
      {!value.is_platform && (value.status === "pending_delete" ? <ConfirmAction label="Cancel delete" description="Cancel deletion and return this organisation to suspended status?" onConfirm={() => refresh(() => adminApi.lifecycle(id, "cancel-delete"))} /> : <div className="actions">
        <label>Grace days<Input type="number" min={1} max={90} step={1} value={days} onChange={(e) => setDays(e.target.value)} /></label>
        <ConfirmAction label="Schedule delete" description={`Block access now and schedule deletion in ${days} days? Purge runs as a background job.`} disabled={!/^\d+$/.test(days) || Number(days) < 1 || Number(days) > 90} onConfirm={() => refresh(() => adminApi.lifecycle(id, "schedule-delete", { grace_days: Number(days) }))} />
      </div>)}
    </section>
    <section><h2>Authentication</h2>{auth.isPending ? <p>Loading authentication…</p> : noAuth ? <p>Panel login only</p> : <><ErrorMessage error={auth.error} />{auth.data && <><p>Adapter: {auth.data.adapter}</p><p>Secret configured: {auth.data.secret_set ? "yes" : "no"}</p><pre>{JSON.stringify(auth.data.config, null, 2)}</pre></>}</>}</section>
    <section><h2>Purge blockers</h2><ErrorMessage error={blockers.error} />
      {blockers.isPending ? <p>Loading blockers…</p> : blockers.data && <>
        {blockers.data.legal_hold && <p>Purge blocked by legal hold</p>}
        {blockers.data.items.map((b) => <p key={`${b.resource}-${b.organization}-${b.kind}`}>{b.resource}: {b.referrers} {b.kind} reference(s) from {b.organization}</p>)}
        {!blockers.data.legal_hold && !blockers.data.items.length && <p>No purge blockers.</p>}
        <p>Purge runs only after the deletion date and when all blockers are cleared.</p>
      </>}
    </section>
    <section><h2>Members</h2><ErrorMessage error={members.error} />
      <Table><TableHeader><TableRow><TableHead>Username</TableHead><TableHead>User ID</TableHead><TableHead>Groups</TableHead><TableHead>Action</TableHead></TableRow></TableHeader>
        <TableBody>{members.data?.items.map((m) => <TableRow key={m.user_id}><TableCell>{m.username ?? "—"}</TableCell><TableCell>{m.user_id}</TableCell><TableCell>{m.groups.join(", ")}</TableCell><TableCell>
          <ConfirmAction label={`Detach ${m.username ?? m.user_id}`} description="Remove this membership? This can remove the last organisation administrator." onConfirm={() => refresh(() => adminApi.detach(id, m.user_id))} />
        </TableCell></TableRow>)}</TableBody>
      </Table>
      <form onSubmit={attach} className="mt-4"><h2>Attach member or update groups</h2>
        <label>User ID<Input name="user_id" required /></label><label>Groups (comma separated)<Input name="groups" placeholder="org-admin, writer, reader" /></label>
        <ErrorMessage error={error} /><Button type="submit" disabled={pending}>Save membership</Button>
      </form>
    </section><AuditPanel tenant={id} />
  </>;
}
