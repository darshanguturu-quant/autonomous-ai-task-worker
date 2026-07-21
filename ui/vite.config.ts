import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// Built output (ui/dist) is served by FastAPI itself - `npm run dev` is only
// needed while editing the UI, and proxies API calls to the running backend.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
