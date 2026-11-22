import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// Web UI: relative asset URLs + a <base href> injected by the backend, so one build works under any
// base path. The apps (`--mode app`, see app/README.md) are served from the root of their own
// origin and nobody injects a <base>: absolute asset URLs, else a reload on /album/5 would look
// for /album/assets/….
export default defineConfig(({ mode }) => ({
  base: mode === "app" ? "/" : "./",
  plugins: [svelte()],
  build: { target: "es2022", sourcemap: false, chunkSizeWarningLimit: 200 },
  server: {
    port: 5173,
    proxy: { "/api": process.env.AUDIUM_DEV_BACKEND ?? "http://127.0.0.1:8080" },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
}));
