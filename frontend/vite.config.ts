// SPDX-License-Identifier: AGPL-3.0-or-later
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Servido pelo FastAPI em "/" com CSP estrita (default-src 'self'):
// nada de scripts/estilos inline nem origens de terceiros no bundle.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    assetsInlineLimit: 0,
    modulePreload: { polyfill: false },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
