"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { adminApi } from "../../lib/api";

import { Button } from "./button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "./dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./table";

export function ErrorMessage({ error }: { error: unknown }) {
  return error ? <p role="alert">{error instanceof Error ? error.message : "Request failed. Please retry."}</p> : null;
}

export function ConfirmAction({ label, description, onConfirm, disabled = false }: {
  label: string;
  description: string;
  onConfirm: () => Promise<unknown>;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function confirm() {
    setPending(true);
    setError(null);
    try { await onConfirm(); setOpen(false); }
    catch (e) { setError(e); }
    finally { setPending(false); }
  }
  return <Dialog open={open} onOpenChange={(next) => { if (!pending) { setOpen(next); setError(null); } }}>
    <DialogTrigger asChild><Button type="button" variant="outline" disabled={disabled}>{label}</Button></DialogTrigger>
    <DialogContent showCloseButton={!pending}>
      <DialogHeader><DialogTitle>{label}</DialogTitle><DialogDescription>{description}</DialogDescription></DialogHeader>
      <ErrorMessage error={error} />
      <DialogFooter>
        <Button type="button" variant="outline" disabled={pending} onClick={() => setOpen(false)}>Cancel</Button>
        <Button type="button" disabled={pending} onClick={confirm}>{pending ? "Working…" : "Confirm"}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}

export function AuditPanel({ tenant }: { tenant?: string }) {
  const [before, setBefore] = useState<number>();
  const audit = useQuery({ queryKey: ["audit", before], queryFn: () => adminApi.audit(before) });
  const rows = audit.data?.items ?? [];
  return <section>
    <h2>Audit log</h2><ErrorMessage error={audit.error} />
    {audit.isPending ? <p>Loading audit log…</p> : <>
      <Table aria-label="Audit log"><TableHeader><TableRow><TableHead>When</TableHead><TableHead>Action</TableHead><TableHead>Actor</TableHead><TableHead>Target</TableHead><TableHead>Details</TableHead></TableRow></TableHeader>
        <TableBody>{rows.filter((r) => !tenant || r.tenant_id === tenant).map((r) => <TableRow key={r.id}>
          <TableCell>{new Date(r.at).toLocaleString()}</TableCell><TableCell>{r.action}</TableCell><TableCell>{r.actor}</TableCell><TableCell>{r.target ?? r.tenant_id ?? "—"}</TableCell><TableCell><pre>{r.detail ? JSON.stringify(r.detail) : "—"}</pre></TableCell>
        </TableRow>)}</TableBody>
      </Table>
      {!rows.length && <p>No audit entries.</p>}
      <div className="actions"><Button variant="outline" disabled={before === undefined} onClick={() => setBefore(undefined)}>Latest</Button>
        <Button variant="outline" disabled={rows.length < 50} onClick={() => setBefore(rows.at(-1)?.id)}>Older</Button></div>
    </>}
  </section>;
}
