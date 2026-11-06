import { headers } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { getLoginToken, getSessionUser } from "@/lib/session";

import { SignOutButton } from "./sign-out-button";

export default async function Home() {
  const incoming = await headers();
  const user = await getSessionUser(incoming);
  if (user === null) redirect("/login");
  const token = await getLoginToken(incoming);
  const me = token ? await fetch(`${process.env.KREP_API_URL ?? "http://localhost:8000"}/v1/me`, {
    headers: { authorization: `Bearer ${token}` }, cache: "no-store", redirect: "error",
  }).then(async (response) => response.ok ? response.json() : null).catch(() => null) : null;
  return (
    <main>
      <h1>krep</h1>
      <p>Signed in as {user.username ?? user.name}</p>
      {me?.is_platform_admin && <p><Link href="/platform/organizations">Platform console</Link></p>}
      <SignOutButton />
    </main>
  );
}
