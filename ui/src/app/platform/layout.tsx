"use client";

import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { ErrorMessage } from "@/components/ui/console";
import { getMe } from "@/lib/api";

import "./platform.css";

function Platform({ children }: { children: React.ReactNode }) {
  const me = useQuery({ queryKey: ["me"], queryFn: () => getMe(), staleTime: 0 });
  return <div className="platform">
    {me.data?.is_platform_admin ? <>
      <nav aria-label="Platform"><Link href="/">krep</Link><Link href="/platform/organizations">Organisations</Link><Link href="/platform/users">Users</Link><Link href="/platform/audit">Audit</Link></nav>
      <main>{children}</main>
    </> : <main>{me.isPending ? <p>Checking access…</p> : <><h1>Platform access required</h1><ErrorMessage error={me.error} /><Link href="/">Return home</Link></>}</main>}
  </div>;
}

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><Platform>{children}</Platform></QueryClientProvider>;
}
