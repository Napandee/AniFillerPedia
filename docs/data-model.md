# Data Model

Series and episode records, and the status vocabulary.

Built and live. Requirements this was built against, kept here as the
rationale behind the shipped schema (see `backend/schema.sql` for the
actual current tables/columns):

- Separate the episode-level community-contributed/correctable layer
  (filler/canon status, source citations) from the series catalog — but note
  the series catalog itself is *not* an auto-synced/rebuildable table the way
  AniDex's AniList-sourced tables are (manami-project's dataset is archived,
  see Data Source), so it's bootstrapped once and then grown the same way
  episode data grows: community proposal + approval, never an unmoderated
  direct write.
- Every entry needs a status (pending/approved) and a citation — no entry
  should be live/authoritative without both a source and at least one
  approval, given the "Wikipedia-style, not open-write" model this project is
  built around.
- An audit trail of who submitted/approved/corrected what — needed for the
  approval-flow model to actually mean something.
