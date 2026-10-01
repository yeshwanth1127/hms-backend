import path from "node:path";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
export default defineConfig({
  base: "/staff/",
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "browser-only-voice-sdk",
      generateBundle(_options, bundle) {
        for (const output of Object.values(bundle)) {
          if (output.type !== "chunk") continue;
          for (const id of Object.keys(output.modules)) {
            if (
              /node_modules\/(speaker|node-gyp|readable-stream)\//.test(id) ||
              /sarvam-conv-ai-sdk\/dist\/interfaces\/node/.test(id)
            ) {
              throw new Error(
                "Node audio dependency must not enter the clinic browser bundle",
              );
            }
          }
        }
      },
    },
  ],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  build: {
    outDir: "../app/staff_static",
    emptyOutDir: true,
    minify: "terser",
    terserOptions: { compress: { drop_console: true } },
    rollupOptions: {
      input: {
        staff: path.resolve(import.meta.dirname, "index.html"),
        talk: path.resolve(import.meta.dirname, "talk.html"),
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5178,
    proxy: { "/api": "http://127.0.0.1:8012" },
  },
});
