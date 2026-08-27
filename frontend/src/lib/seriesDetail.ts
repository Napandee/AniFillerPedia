// #116: shared series-detail resolution logic, used by every locale's own
// src/pages/{,es,hi,ja,zh-cn}/series/[slug].astro wrapper.
//
// This lives in a plain .ts module, NOT in the shared
// components/pages/series/SeriesDetailPage.astro component, for a real,
// verified reason: Astro.redirect() (and, it turns out, Astro.response.status
// too) only take effect when called from the actual page component Astro is
// routing to — calling either from a nested/child .astro component throws
// AstroError [ResponseSentError] (redirect) or silently no-ops (response
// status), confirmed by actually running the built server and curling a
// legacy numeric URL and an unknown slug. So each per-locale page file calls
// resolveSeriesDetail() itself (cheap — a redirect check costs one extra
// fetch only for the rare legacy-numeric-URL case, since a real slug never
// matches the numeric-id regex below) and handles the redirect/404 status
// itself; SeriesDetailPage.astro stays a pure rendering component, given the
// already-resolved result as a prop.
import { createApiClient } from "../api/client";
import type { components } from "../api/schema";

export type SeriesDetailOut = components["schemas"]["SeriesDetailOut"];
export type EpisodeOut = components["schemas"]["EpisodeOut"];

export type SeriesDetailResolution =
  | { kind: "redirect"; to: string }
  | { kind: "not-found" }
  | { kind: "found"; series: SeriesDetailOut; episodes: EpisodeOut[] };

export async function resolveSeriesDetail(
  rawSlugParam: string,
  apiBaseUrl: string,
  buildRedirectUrl: (slug: string) => string
): Promise<SeriesDetailResolution> {
  if (rawSlugParam === "") {
    return { kind: "not-found" };
  }

  const api = createApiClient(apiBaseUrl);
  // A real slug (services/slugs.py's output) is never purely digits — it
  // always contains at least one letter, since slugify_title falls back to
  // "series" for a title that slugifies to nothing. So this check never
  // false-positives on a genuine slug.
  const paramLooksNumeric = /^[0-9]+$/.test(rawSlugParam);

  const { data: seriesData, response } = await api.GET("/api/v1/series/{id_or_slug}", {
    params: { path: { id_or_slug: rawSlugParam } },
  });

  if (response.status === 404 || !seriesData) {
    return { kind: "not-found" };
  }

  if (paramLooksNumeric) {
    // A legacy numeric URL that resolved to a real series — redirect to its
    // canonical slug URL rather than rendering the page body under the old
    // URL. `slug` is guaranteed non-null here in practice (every series is
    // backfilled by #116's migration before this code ships), but fall back
    // to the numeric id itself in the theoretical case it's still null,
    // rather than building a "/series/null" URL.
    return { kind: "redirect", to: buildRedirectUrl(seriesData.slug ?? String(seriesData.id)) };
  }

  const { data: episodesData } = await api.GET("/api/v1/series/{series_id}/episodes", {
    params: { path: { series_id: seriesData.id } },
  });
  // An empty array is a normal, valid response (zero-episode series) — `?? []`
  // only guards against a genuinely failed/undefined fetch.
  const episodes = (episodesData ?? []).slice().sort((a, b) => a.episode_number - b.episode_number);

  return { kind: "found", series: seriesData, episodes };
}
