import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
export default defineConfig({
  base: "/staff/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  build: { outDir: "../app/staff_static", emptyOutDir: true },
  server: {
    host: "127.0.0.1",
    port: 5178,
    proxy: { "/api": "http://127.0.0.1:8012" },
  },
});
