import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { getSessionUser } from "@/lib/session";

import { SignOutButton } from "./sign-out-button";

export default async function Home() {
  const user = await getSessionUser(await headers());
  if (user === null) redirect("/login");
  return (
    <main>
      <h1>krep</h1>
      <p>Signed in as {user.username ?? user.name}</p>
      <SignOutButton />
    </main>
  );
}
