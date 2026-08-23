-- #77: citations.description was doing two jobs at once — a short,
-- reader-facing "here's the source" claim, and the full compiled research/
-- methodology trail (cross-reference notes, internal decision references,
-- "not recorded at compile time" caveats). Splitting the latter out into
-- its own nullable field lets the frontend show a short description by
-- default and tuck the full trail behind a "How was this verified?"
-- disclosure, rather than showing both mixed into one long paragraph on
-- every single episode.
ALTER TABLE citations ADD COLUMN methodology_note TEXT;
