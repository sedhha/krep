import { describe, expect, it, vi } from "vitest";

import { banUser } from "../../src/lib/ban";

describe("banUser", () => {
  it("bans in Better Auth and disables in the registry", async () => {
    const ban = vi.fn(async () => {});
    const disable = vi.fn(async () => {});
    await banUser("u1", { ban, disable });
    expect(ban).toHaveBeenCalledWith("u1");
    expect(disable).toHaveBeenCalledWith("u1");
  });

  it("still disables when the Better Auth ban fails, then reports the failure", async () => {
    const ban = vi.fn(async () => {
      throw new Error("auth down");
    });
    const disable = vi.fn(async () => {});
    await expect(banUser("u1", { ban, disable })).rejects.toThrow("auth down");
    expect(disable).toHaveBeenCalledWith("u1");
  });

  it("still bans when the registry disable fails, then reports the failure", async () => {
    const ban = vi.fn(async () => {});
    const disable = vi.fn(async () => {
      throw new Error("api down");
    });
    await expect(banUser("u1", { ban, disable })).rejects.toThrow("api down");
    expect(ban).toHaveBeenCalledWith("u1");
  });

  it("can be retried after a partial failure", async () => {
    let failOnce = true;
    const ban = vi.fn(async () => {});
    const disable = vi.fn(async () => {
      if (failOnce) {
        failOnce = false;
        throw new Error("api down");
      }
    });
    await expect(banUser("u1", { ban, disable })).rejects.toThrow();
    await expect(banUser("u1", { ban, disable })).resolves.toBeUndefined();
  });
});
