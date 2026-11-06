import { defineConfig } from "@playwright/test";

import { API_PORT, stackEnv, UI_PORT, UI_URL } from "./tests/e2e/constants";

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { baseURL: UI_URL },
  webServer: [
    {
      command: `node ui/tests/e2e/prepare.mjs && uv run uvicorn krep.api:app --port ${API_PORT}`,
      cwd: "..",
      port: API_PORT,
      env: stackEnv,
      reuseExistingServer: false,
      timeout: 180_000,
    },
    {
      command: `pnpm exec next dev -p ${UI_PORT}`,
      port: UI_PORT,
      env: stackEnv,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
