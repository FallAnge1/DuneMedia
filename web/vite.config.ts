import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В разработке API и медиа проксируются на `wrangler dev` (порт 8787).
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true, target: "es2022" },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8787",
      "/media": "http://localhost:8787",
    },
  },
});
