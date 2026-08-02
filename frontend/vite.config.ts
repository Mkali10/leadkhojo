import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// The API base is a relative path in every environment. In development this
// proxy makes the browser see one origin, which means no CORS preflight and
// no base URL baked into the bundle; in production the built assets are
// served from the same origin as the API. Nothing here ever talks to Python
// directly — the REST contract is the only coupling.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    // Loopback only. The API it proxies to has no authentication.
    host: "127.0.0.1",
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/healthz": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/readyz": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
