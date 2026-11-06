export interface BanDeps {
  ban: (userId: string) => Promise<void>;
  disable: (userId: string) => Promise<void>;
}

export async function banUser(userId: string, deps: BanDeps): Promise<void> {
  const results = await Promise.allSettled([deps.ban(userId), deps.disable(userId)]);
  for (const result of results) {
    if (result.status === "rejected") throw result.reason;
  }
}
