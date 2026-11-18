import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// ES-module single-file build: the Jinja template drops
// <script type="module" src="/static/assistant/assistant.js"> and
// <link rel="stylesheet" href="/static/assistant/style.css"> into admin
// pages; the module self-mounts onto #lawbench-assistant-root. (An IIFE
// build was tried first and died silently mid-execution at 17 MB — classic
// scripts of this size with this dependency graph are fragile; modules are
// the well-trodden island path.)
export default defineConfig({
  plugins: [react()],
  // CopilotKit's client references Node's `process.env` at module top level,
  // which throws `process is not defined` in the browser — replace both the
  // common .NODE_ENV lookups and any bare process.env access.
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
    "process.env": '{"NODE_ENV":"production"}',
  },
  build: {
    outDir: "../src/web/static/assistant",
    emptyOutDir: true,
    cssCodeSplit: false,
    // lib-mode builds do not inherit the default minifier — set it explicitly.
    minify: "esbuild",
    lib: {
      entry: "src/main.tsx",
      formats: ["es"],
      fileName: () => "assistant.js",
    },
    chunkSizeWarningLimit: 4000,
  },
});
