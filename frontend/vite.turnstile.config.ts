import { defineConfig } from "vite";

// Second origin: the static Turnstile frame page (ADR 0016 point 7). No React, no app code.
export default defineConfig({
  root: "turnstile",
  envDir: "..",
  server: { port: 5174, strictPort: true },
  build: {
    outDir: "../dist-turnstile",
    emptyOutDir: true,
    assetsInlineLimit: 0,
    sourcemap: false,
    rollupOptions: { input: "turnstile/turnstile.html" },
  },
});
