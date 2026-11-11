import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname),
      "server-only": path.resolve(import.meta.dirname, "test/stubs/server-only.ts"), // the real package throws outside a React Server Components build
    },
  },
  test: {
    environment: "node", // component tests opt in to jsdom with a `// @vitest-environment jsdom` comment
    include: ["test/**/*.test.{ts,tsx}"],
    setupFiles: ["test/setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["lib/**/*.ts", "app/**/route.ts", "proxy.ts"],
    },
  },
});
