import Link from "next/link";

import { signupAllowed } from "@/lib/auth";

import { SignupForm } from "./signup-form";

export default function SignupPage() {
  return (
    <main>
      <h1>Create an account</h1>
      {signupAllowed ? (
        <SignupForm />
      ) : (
        <p>
          Sign-up is disabled. <Link href="/login">Sign in</Link>
        </p>
      )}
    </main>
  );
}
