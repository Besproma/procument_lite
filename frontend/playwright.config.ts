import { devices, defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "../tests/e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chrome",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
  webServer: [
    {
      command:
        "cd .. && PYTHONPATH=backend/src:. python3 -m uvicorn test_support.local_server:app --host 127.0.0.1 --port 8000",
      url: "http://127.0.0.1:8000/health/ready",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
