"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState, useSyncExternalStore } from "react";

import { authClient } from "@/lib/auth-client";

const subscribe = () => () => {};

export default function LoginPage() {
  const ready = useSyncExternalStore(subscribe, () => true, () => false);
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const passwordInput = event.currentTarget.elements.namedItem("password");
    if (passwordInput instanceof HTMLInputElement) passwordInput.value = "";
    setPending(true);
    setError(null);
    const { error } = await authClient.signIn.username({
      username: String(form.get("username")),
      password: String(form.get("password")),
    });
    setPending(false);
    if (error) {
      setError("Invalid username or password");
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <main>
      <h1>Sign in</h1>
      <form method="post" onSubmit={onSubmit}>
        <label>
          Username
          <input name="username" disabled={!ready || pending} autoComplete="username" required />
        </label>
        <label>
          Password
          <input name="password" type="password" disabled={!ready || pending} autoComplete="current-password" required />
        </label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={!ready || pending}>
          Sign in
        </button>
      </form>
      <p>
        <Link href="/signup">Create an account</Link>
      </p>
    </main>
  );
}
