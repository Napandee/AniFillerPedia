-- Lightweight "related series" links for shows split across multiple
-- AniList catalog entries (e.g. Fairy Tail / Fairy Tail (2014) /
-- Fairy Tail (2018)) — decided 2026-08-22 over a heavier "collection"
-- grouping construct, since the exact same structural pattern (Naruto /
-- Naruto: Shippuuden) is already handled today as two fully separate
-- catalog rows, each with its own absolute episode numbering, and this
-- project's own bias is against building for demand not yet observed
-- across enough shows to justify it.
--
-- Directed pairs, not an undirected/symmetric constraint at the schema
-- level — whoever links two series is expected to insert both directions
-- (A->B and B->A) so a plain `WHERE series_id = ?` query on either side
-- finds the relation without a UNION. The CHECK just rules out a series
-- linking to itself.
CREATE TABLE series_relations (
    series_id         INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    related_series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    PRIMARY KEY (series_id, related_series_id),
    CHECK (series_id != related_series_id)
);
