"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { ErrorMessage } from "@/components/ui/console";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { adminApi } from "@/lib/api";

export default function OrganizationsPage() {
  const orgs = useQuery({ queryKey: ["organizations"], queryFn: adminApi.organizations });
  return <><h1>Organisations</h1><div className="actions"><Button asChild><Link href="/platform/organizations/new">New organisation</Link></Button></div>
    <section><ErrorMessage error={orgs.error} />
      {orgs.isPending ? <p>Loading organisations…</p> : <Table>
        <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Slug</TableHead><TableHead>Status</TableHead><TableHead>Legal hold</TableHead></TableRow></TableHeader>
        <TableBody>{orgs.data?.items.map((org) => <TableRow key={org.id}>
          <TableCell><Link href={`/platform/organizations/${org.id}`}>{org.name}</Link></TableCell><TableCell>{org.slug}</TableCell><TableCell>{org.status}</TableCell><TableCell>{org.legal_hold ? "Yes" : "No"}</TableCell>
        </TableRow>)}</TableBody>
      </Table>}
    </section></>;
}
