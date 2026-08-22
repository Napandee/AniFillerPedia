// #46: cover art for the series detail page and home grid. AniList's public
// GraphQL API needs no auth for this query and already has everything we
// need — no AniFillerPedia schema change, since `series.anilist_id` already
// exists and covers ~97% of the bootstrap-imported catalog (see #46).
//
// Always batches every id into ONE request (`Page(media(id_in: $ids))`)
// rather than one request per series — the home grid renders up to ~26
// series per load (20 grid + 6 teaser) and this must not turn into 26
// outbound calls.
export interface AniListCover {
  coverImageUrl: string | null;
  bannerImageUrl: string | null;
}

const ANILIST_ENDPOINT = "https://graphql.anilist.co";

const QUERY = `
  query ($ids: [Int]) {
    Page(perPage: 50) {
      media(id_in: $ids, type: ANIME) {
        id
        coverImage { extraLarge }
        bannerImage
      }
    }
  }
`;

/**
 * Fetches cover/banner art for a batch of AniList ids. Never throws — a
 * network failure, timeout, or malformed response all just come back as an
 * empty map, and callers treat a missing entry exactly like "no anilist_id
 * at all": render the generated fallback (CoverFallback.astro), never block
 * or error the page over a missing cover-art provider.
 */
export async function fetchAniListCovers(anilistIds: (number | null | undefined)[]): Promise<Map<number, AniListCover>> {
  const ids = [...new Set(anilistIds.filter((id): id is number => typeof id === "number" && Number.isFinite(id)))];
  const result = new Map<number, AniListCover>();
  if (ids.length === 0) return result;

  try {
    const response = await fetch(ANILIST_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ query: QUERY, variables: { ids } }),
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) return result;

    const body = await response.json();
    const media = body?.data?.Page?.media;
    if (!Array.isArray(media)) return result;

    for (const entry of media) {
      if (typeof entry?.id !== "number") continue;
      result.set(entry.id, {
        coverImageUrl: typeof entry.coverImage?.extraLarge === "string" ? entry.coverImage.extraLarge : null,
        bannerImageUrl: typeof entry.bannerImage === "string" ? entry.bannerImage : null,
      });
    }
    return result;
  } catch {
    return result;
  }
}
