import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.API_PROXY_TARGET || "http://127.0.0.1:8000";
  return {
    plugins: [react()],
    server: { proxy: { "/api": { target }, "/ws": { target, ws: true } } },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      globals: true,
      restoreMocks: true,
      sequence: { concurrent: false },
      maxWorkers: 2,
    },
  };
});
