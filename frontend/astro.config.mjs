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
  // #63: the real production origin — Layout.astro uses Astro.site to build
  // canonical/Open Graph URLs and sitemap.xml.ts uses it for every <loc>,
  // so both stay correct without hardcoding the domain in two places.
  site: "https://anifillerpedia.wiki",
  // Astro's CSRF origin-check middleware (on by default for every non-GET
  // request) rejects the request's Host header entirely unless it appears
  // here — with an empty list it silently falls back to a bare "localhost"
  // with no port, which then never matches any real Origin header, so
  // every form POST (e.g. #37's logout) 403s. Found by actually running the
  // logout flow end to end, not by reading the docs; the domain list
  // matches this app's two real hosts (dev, and the production domain from
  // CLAUDE.local.md) rather than disabling the check.
  security: {
    allowedDomains: [{ hostname: "anifillerpedia.wiki" }, { hostname: "localhost" }],
  },
  // #106: UI translation. Languages picked to match Napandee/AniDex's own
  // i18n precedent (#139/#143 there) — top 5 world languages by speaker
  // count. `prefixDefaultLocale: false` keeps English at the bare `/` (no
  // `/en/` prefix) so every existing URL keeps working unchanged; the other
  // four get a path prefix (`/es/...`, `/hi/...`, `/ja/...`, `/zh-cn/...`).
  // Path-based, not a cookie/account setting like AniDex's — this site is
  // anonymous-first (no persistent per-visitor identity to hang a
  // preference off), and path-based locales stay independently indexable
  // by search engines, consistent with #63's existing SEO investment.
  i18n: {
    defaultLocale: "en",
    locales: ["en", "es", "hi", "ja", "zh-cn"],
    routing: {
      prefixDefaultLocale: false,
    },
  },
  // #41: the API docs / contribute pages render the repo's own docs/API.md
  // and CONTRIBUTING.md (one directory above `frontend/`) via a `?raw`
  // import rather than hand-copying their prose — Vite restricts fs access
  // to the project root by default, so reaching one level up needs this
  // explicit allow. Additive to the existing output/adapter/security keys
  // above (owned by #31/#37) — nothing else here changed.
  vite: {
    server: {
      fs: {
        allow: [".."],
      },
    },
  },
});
