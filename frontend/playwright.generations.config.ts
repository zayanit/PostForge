import { defineConfig } from "@playwright/test";

// This suite owns its auth fixture and mocks provider/API responses. No real
// Supabase stack or paid image requests are used.
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: [
    "generations.spec.ts",
    "signup-flow.spec.ts",
    "session-enforcement.spec.ts",
  ],
  workers: 1,
  fullyParallel: false,
  use: { baseURL: "http://127.0.0.1:3011", trace: "retain-on-failure" },
  webServer: process.env.PLAYWRIGHT_EXTERNAL_SERVER
    ? undefined
    : {
        command:
          "node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 3011",
        url: "http://127.0.0.1:3011/login",
        reuseExistingServer: false,
        timeout: 120000,
        env: {
          NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:54329",
          NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "test-only-publishable-key",
          NEXT_PUBLIC_API_URL: "/api",
          NEXT_SERVER_API_URL: "http://127.0.0.1:54328",
        },
      },
});
