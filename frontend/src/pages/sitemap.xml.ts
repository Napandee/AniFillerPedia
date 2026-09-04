import type { APIRoute } from "astro";
import { createApiClient } from "../api/client";
import { SUPPORTED_LOCALES } from "../i18n/ui";
import { getRelativeLocaleUrl } from "astro:i18n";

// #63: a real, dynamic sitemap — not @astrojs/sitemap's static-route
// discovery, which only knows about routes it can enumerate at build time.
// This site is deliberately SSR (CLAUDE.md Architecture: no rebuild-trigger
// pipeline for freshness), so series pages come and go without a build at
// all; a static sitemap would go stale the moment a series is added. This
// route queries the backend at request time instead, the same way every
// other page on this site already does.
//
// Paginates through the default GET /series listing (no q/id params) —
// which already excludes zero-episode stubs per #47 — rather than a
// separate query, since "worth showing in the public browse grid" and
// "worth telling Google to index" are the same bar.
const STATIC_PATHS = [
  "",
  "contribute",
  "docs",
  "license",
  "privacy",
  "tos",
  "export-access",
  "propose-series",
  // #153/#154: public, unauthenticated, English-only discovery pages —
  // same indexability bar as the rest of this list.
  "needs-research",
  "activity",
];

// #106: only home (`""`) and series pages are actually translated in this
// first cut (per that issue's own scope) — the other STATIC_PATHS entries
// above still render English content at a locale-prefixed URL, so listing
// e.g. /es/docs/ here would tell Google to index a page that isn't really
// Spanish. Add locale variants only for what's genuinely localized.
const LOCALIZED_PATHS = [""];
const NON_DEFAULT_LOCALES = SUPPORTED_LOCALES.filter((l) => l !== "en");

function urlEntry(loc: string): string {
  return `  <url><loc>${loc}</loc></url>`;
}

export const GET: APIRoute = async ({ site }) => {
  const baseUrl = import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const api = createApiClient(baseUrl);
  const origin = site?.toString().replace(/\/$/, "") ?? "https://anifillerpedia.wiki";

  // #116: slugs, not numeric ids — the canonical series URL is now
  // /series/{slug}. Falls back to the numeric id for the vanishingly rare
  // case of a series whose slug backfill hasn't reached it yet (never true
  // in production after the #116 migration's backfill runs, but avoids
  // emitting a literal "null" segment if it ever were).
  const seriesSlugs: string[] = [];
  const limit = 100;
  let offset = 0;
  // Bounded to a sane number of pages so a backend error/loop can't hang
  // this request forever — the real catalog is a few hundred series today.
  for (let page = 0; page < 100; page++) {
    const { data } = await api.GET("/api/v1/series", { params: { query: { limit, offset } } });
    if (!data || data.items.length === 0) break;
    seriesSlugs.push(...data.items.map((item) => item.slug ?? String(item.id)));
    offset += limit;
    if (offset >= data.total) break;
  }

  const urls = [
    ...STATIC_PATHS.map((path) => urlEntry(`${origin}/${path}`)),
    ...seriesSlugs.map((slug) => urlEntry(`${origin}/series/${slug}`)),
    ...NON_DEFAULT_LOCALES.flatMap((locale) => [
      ...LOCALIZED_PATHS.map((path) => urlEntry(`${origin}${getRelativeLocaleUrl(locale, `/${path}`)}`)),
      ...seriesSlugs.map((slug) => urlEntry(`${origin}${getRelativeLocaleUrl(locale, `/series/${slug}`)}`)),
    ]),
  ];

  const body =
    `<?xml version="1.0" encoding="UTF-8"?>\n` +
    `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join("\n")}\n</urlset>\n`;

  return new Response(body, {
    headers: { "Content-Type": "application/xml; charset=utf-8" },
  });
};
