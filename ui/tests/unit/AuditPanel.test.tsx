// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AuditPanel } from "../../src/components/ui/console";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the latest 100 entries and leaves older-log retrieval to the API", async () => {
  const requests: string[] = [];
  vi.stubGlobal("fetch", async (input: string) => {
    requests.push(input);
    return Response.json({ items: Array.from({ length: 100 }, (_, index) => ({
      id: 200 - index, actor: "admin", action: `test.event.${index}`, tenant_id: null,
      target: null, detail: null, at: "2026-11-07T00:00:00Z",
    })) });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><AuditPanel /></QueryClientProvider>);
  await screen.findByText("test.event.99");
  expect(within(screen.getByRole("table", { name: "Audit log" })).getAllByRole("row")).toHaveLength(101);
  expect(requests).toEqual(["/api/v1/admin/audit?limit=100"]);
  expect(screen.queryByRole("button", { name: "Older" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Latest" })).toBeNull();
});
