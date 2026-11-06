"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState, useSyncExternalStore } from "react";

import { authClient } from "@/lib/auth-client";

const subscribe = () => () => {};

export function SignupForm() {
  const ready = useSyncExternalStore(subscribe, () => true, () => false);
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const passwordInput = event.currentTarget.elements.namedItem("password");
    if (passwordInput instanceof HTMLInputElement) passwordInput.value = "";
    const username = String(form.get("username"));
    setPending(true);
    setError(null);
    const { error } = await authClient.signUp.email({
      username,
      name: username,
      email: String(form.get("email")),
      password: String(form.get("password")),
    });
    setPending(false);
    if (error) {
      setError(error.message ?? "Could not create the account");
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <form method="post" onSubmit={onSubmit}>
      <label>
        Username
        <input name="username" disabled={!ready || pending} autoComplete="username" minLength={3} required />
      </label>
      <label>
        Email
        <input name="email" type="email" disabled={!ready || pending} autoComplete="email" required />
      </label>
      <label>
        Password
        <input name="password" type="password" disabled={!ready || pending} autoComplete="new-password" minLength={8} required />
      </label>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={!ready || pending}>
        Create account
      </button>
      <p>
        <Link href="/login">Already have an account?</Link>
      </p>
    </form>
  );
}
