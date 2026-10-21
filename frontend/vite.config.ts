import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// Relative asset URLs + a <base href> injected by the backend: one build works under any base path.
export default defineConfig({
  base: "./",
  plugins: [svelte()],
  build: { target: "es2022", sourcemap: false, chunkSizeWarningLimit: 200 },
  server: {
    port: 5173,
    proxy: { "/api": process.env.AUDIUM_DEV_BACKEND ?? "http://127.0.0.1:8080" },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
