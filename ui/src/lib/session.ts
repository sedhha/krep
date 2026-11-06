import { auth } from "@/lib/auth";

export async function getSessionUser(headers: Headers) {
  const session = await auth.api.getSession({ headers });
  return session?.user ?? null;
}

export async function getLoginToken(headers: Headers): Promise<string | null> {
  if ((await getSessionUser(headers)) === null) return null;
  try {
    const { token } = await auth.api.getToken({ headers });
    return token;
  } catch {
    return null;
  }
}
