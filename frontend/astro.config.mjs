import { defineConfig } from "astro/config";
import node from "@astrojs/node";

// SSR/on-demand rendering, not a static prebuild — freshness for
// series/episode pages comes from the outbox-driven Cloudflare cache purge
// on approval, not a rebuild-trigger pipeline (CLAUDE.md Architecture).
// "standalone" mode runs its own Node HTTP server, matching the
// self-hosted-runner/docker-compose deploy pattern the backend already uses.
export default defineConfig({
  output: "server",
  adapter: node({ mode: "standalone" }),
});
