# #196 Pagination Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two Minor findings from the pre-merge review of #196 (pagination on `GET /contributions`, `GET /contributions/mine`, `GET /contributions/mine/votes`): (1) the GDPR export endpoint has no regression test proving it actually returns every row a user has, beyond the paginated endpoints' page-size defaults/caps; (2) the "Load more" client script is duplicated near-identically between `account.astro` and `admin/moderation.astro`.

**Architecture:** Task 1 is backend-only: add one real-Postgres test to the existing GDPR test file, seeding more rows (via the bulk-submission endpoint, to stay under the single-submission rate limit) than any pagination default/cap in this API ever returns in one call, then asserting the export endpoint returns all of them. Task 2 is frontend-only: extract the fetch/paging state machine both pages already implement into one shared `frontend/src/lib/loadMore.ts` module (an ES module imported from each page's own `<script>` block — a new but standard Astro pattern for this codebase, verified via `astro build`), leaving each page's own DOM-building/wiring code in place since that part is genuinely page-specific.

**Tech Stack:** FastAPI/pytest/httpx/asyncpg (Task 1); Astro/TypeScript, plain DOM APIs, no framework (Task 2).

**Spec:** No separate spec doc — this plan implements the "Issues" section of the #196 pre-merge review conducted in this session (findings below), not a new feature.

Review findings this plan addresses:
- **Minor #1:** No test exercises the GDPR export path's contribution/vote arrays post-#196 change — a regression test would make a future reintroduction of the sentinel-limit anti-pattern (already fixed once in commit `3f5216d`) fail loudly instead of silently.
- **Minor #2:** `account.astro`'s and `moderation.astro`'s "Load more" logic duplicates near-identical fetch/append/button-state code.

## Global Constraints

- Never string-interpolate SQL — parameterized queries only (existing project-wide rule, unaffected by this plan but binding on any new query).
- Every new/changed test must run against the real local test-pg instance (`postgresql+asyncpg://anifillerpedia:testpass@127.0.0.1:55432/anifillerpedia`), not mocked — matches this codebase's established convention (see `backend/tests/test_trust_gdpr_tos.py`'s own docstring: "Same real-DB, test-data-prefixed, dedicated-fixture convention").
- Frontend changes must pass `astro check` and `astro build` clean (no new type errors) — this codebase has no Chromium available for browser testing; verification is via SSR HTML / compiled-bundle inspection, same as every prior frontend task in this project.
- Each task ends in its own commit referencing its own GitHub issue with a closing keyword (`Fixes #<n>`), per this repo's Guardrails.

---

## Task 1: GDPR export completeness regression test

**Files:**
- Modify: `backend/tests/test_trust_gdpr_tos.py:217-221` (insert new test immediately after `test_users_me_export_bundles_everything`, before `test_users_me_export_requires_authentication` at line 224)

**Interfaces:**
- Consumes: existing helpers in this file — `_make_user(role="contributor", email=None) -> int`, `_delete_user(user_id) -> None`, `_make_test_series(title_suffix) -> int`, `_cleanup_series(series_id) -> None`, `_cookie(user_id) -> dict`, `_vote_as(user_id, contribution_id, vote) -> Response`. Also calls the real HTTP endpoints `POST /api/v1/series/{series_id}/contributions/bulk` (schema: `BulkContributionCreate` — `canon_ranges: str`, `citation: {"description": str}`, `license_accepted: bool`; response `BulkContributionResult` — `created: list[{episode_number, contribution_id, proposed_status}]`) and `GET /api/v1/users/me/export` (response has top-level `contributions: list`, `votes: list`).
- Produces: nothing consumed by later tasks — this is a leaf test.

Why the bulk endpoint, not the single-submission one used by the existing `test_users_me_export_bundles_everything`: `POST /api/v1/contributions` (single-episode) is rate-limited to 20 calls/hour per user (`CONTRIBUTION_SUBMIT_RATE_LIMIT = 20` in `backend/services/contributions.py`) — seeding more than 20 rows via that path would 429 partway through. `POST /series/{series_id}/contributions/bulk` creates many rows in **one** call (up to 2000 per call, rate-limited separately at 10 *calls*/24h — `BULK_SUBMISSION_RATE_LIMIT = 10`), so one call per user seeds the whole batch with no risk of tripping either limit.

Why 105, not just "more than 20": the paginated siblings this export endpoint must NOT behave like (`GET /contributions/mine`, `GET /contributions/mine/votes`) default to `limit=20` and cap at `limit<=100`. Seeding only e.g. 25 rows would only prove the export beats the *default* page size, not the *hard cap* — a regression that reintroduced a call to the paginated service function with `limit=100` instead of a genuine unbounded fetch would still pass a 25-row test. 105 exceeds both.

- [ ] **Step 1: Write the failing test**

Insert immediately after line 221 (`await _delete_user(other_id)`, the end of `test_users_me_export_bundles_everything`'s `finally` block) and before the blank-line-then-`@pytest.mark.asyncio` at line 223-224:

```python
@pytest.mark.asyncio
async def test_users_me_export_includes_every_contribution_and_vote_beyond_any_page_cap() -> None:
    """#196 review follow-up: GET /users/me/export's whole legal purpose is
    "every row this user has, unabridged" — it must never behave like the
    paginated GET /contributions/mine / GET /contributions/mine/votes
    (default limit=20, hard cap limit<=100). Seeds 105 contributions and
    105 votes for one user (via the bulk-submission endpoint, to seed each
    batch in one call rather than tripping the single-submission
    endpoint's 20/hour rate limit) and asserts the export returns all 105
    of each — a number chosen specifically to exceed both the paginated
    siblings' default AND their hard cap, so this test fails if a future
    change ever reintroduces a call to those paginated functions here
    (with any limit value) instead of the genuinely unbounded
    list_my_contributions_all()/list_my_votes_all() added in 3f5216d.
    """
    caller_id = await _make_user(email="export-completeness@example.com")
    other_id = await _make_user()
    series_id = await _make_test_series("export-completeness")
    try:
        seed_count = 105
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(caller_id)) as client:
            bulk_resp = await client.post(
                f"/api/v1/series/{series_id}/contributions/bulk",
                json={
                    "canon_ranges": f"1-{seed_count}",
                    "citation": {"description": f"{TEST_PREFIX} bulk citation (caller)"},
                    "license_accepted": True,
                },
            )
        assert bulk_resp.status_code == 200, bulk_resp.text
        assert len(bulk_resp.json()["created"]) == seed_count

        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(other_id)) as client:
            other_bulk_resp = await client.post(
                f"/api/v1/series/{series_id}/contributions/bulk",
                json={
                    "canon_ranges": f"{seed_count + 1}-{seed_count * 2}",
                    "citation": {"description": f"{TEST_PREFIX} bulk citation (other, for votes)"},
                    "license_accepted": True,
                },
            )
        assert other_bulk_resp.status_code == 200, other_bulk_resp.text
        other_contribution_ids = [entry["contribution_id"] for entry in other_bulk_resp.json()["created"]]
        assert len(other_contribution_ids) == seed_count

        for contribution_id in other_contribution_ids:
            vote_resp = await _vote_as(caller_id, contribution_id, "endorse")
            assert vote_resp.status_code == 200, vote_resp.text

        async with AsyncClient(transport=transport, base_url="http://test", cookies=_cookie(caller_id)) as client:
            export_resp = await client.get("/api/v1/users/me/export")
        assert export_resp.status_code == 200, export_resp.text
        body = export_resp.json()

        assert len(body["contributions"]) == seed_count
        assert len(body["votes"]) == seed_count
    finally:
        await _cleanup_series(series_id)
        await _delete_user(caller_id)
        await _delete_user(other_id)


```

- [ ] **Step 2: Run test to verify it currently passes (this is a regression test against already-fixed code, not new behavior)**

Run: `cd backend && python -m pytest tests/test_trust_gdpr_tos.py::test_users_me_export_includes_every_contribution_and_vote_beyond_any_page_cap -v`
Expected: PASS (commit `3f5216d` already shipped the genuinely-unbounded `list_my_contributions_all`/`list_my_votes_all` this test is guarding — this test is not expected to fail; its job is to make the *next* regression fail loudly). If it fails, that is itself a real, currently-live bug in production-bound code and must be investigated before continuing, not worked around in the test.

- [ ] **Step 3: Run the full backend test suite to confirm no other test regressed**

Run: `cd backend && python -m pytest -v 2>&1 | tail -40`
Expected: same pass/fail counts as the #196 PR's own baseline (343 passed / 9 pre-existing failures — 4 unrelated + 5 AniList-outage, tracked in #237), plus this one new passing test.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_trust_gdpr_tos.py
git commit -m "$(cat <<'EOF'
Add regression test for GDPR export completeness beyond any page cap

GET /users/me/export's whole legal purpose is "every row, unabridged" —
seed 105 contributions and 105 votes (via one bulk-submission call each,
to avoid the single-submission endpoint's 20/hour rate limit) and assert
the export returns all of them. 105 exceeds both the paginated sibling
endpoints' default page size (20) and their hard cap (100), so this test
would catch a future regression to either value, not just the default.

Fixes #<ISSUE_1>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LEuvh355uWNpbf7hx6sgQc
EOF
)"
```

---

## Task 2: De-duplicate "Load more" client-script logic into a shared module

**Files:**
- Create: `frontend/src/lib/loadMore.ts`
- Modify: `frontend/src/pages/account.astro` (the `<script>` block starting at line 195 — replace the local `wireLoadMore<T>()` function and its two call sites)
- Modify: `frontend/src/pages/admin/moderation.astro` (the `<script>` block starting at line 369 — replace `wireContribLoadMore()`'s inline fetch logic)

**Interfaces:**
- Produces (consumed by both `.astro` files): `frontend/src/lib/loadMore.ts` exports one function:
  ```ts
  export interface LoadMoreOptions<T> {
    button: HTMLButtonElement;
    buildUrl: (offset: number) => string;
    onRow: (row: T) => void;
    onBatchComplete?: (rows: T[], total: number) => void;
    onError?: (message: string) => void;
  }
  export function wireLoadMore<T>(options: LoadMoreOptions<T>): void;
  ```
  `onRow` is called once per fetched row, in order — the caller is responsible for building AND appending (and, in moderation.astro's case, wiring up approve/reject handlers on) whatever DOM node that row needs; this module owns only the fetch/offset/button-label/removal state machine, never rendering. `onBatchComplete` fires once after all rows in one response have been passed to `onRow` (moderation.astro uses this to refresh its bulk-selection bar/empty-state; account.astro doesn't need it and omits it).

- [ ] **Step 1: Write `frontend/src/lib/loadMore.ts`**

```ts
// #196 review follow-up: shared client-side "Load more" pagination wiring.
// account.astro and admin/moderation.astro each implemented near-identical
// fetch/offset/button-label state machines independently when #196 added
// pagination envelopes to GET /contributions/mine, GET /contributions/mine/votes,
// and GET /contributions — this module is the one shared copy of that state
// machine. It deliberately does NOT know how to build or append a DOM node:
// each page's rows look different (moderation.astro's cards carry
// approve/reject buttons and bulk-selection checkboxes; account.astro's
// don't), so rendering + any per-row wiring stays the caller's job via
// `onRow`. Fetches always use a relative URL built by the caller — never a
// ${baseUrl}-prefixed one (see #218/#228's baked-internal-hostname bug).

export interface LoadMoreOptions<T> {
  button: HTMLButtonElement;
  buildUrl: (offset: number) => string;
  onRow: (row: T) => void;
  onBatchComplete?: (rows: T[], total: number) => void;
  onError?: (message: string) => void;
}

interface PagedEnvelope<T> {
  items: T[];
  total: number;
}

export function wireLoadMore<T>(options: LoadMoreOptions<T>): void {
  const { button, buildUrl, onRow, onBatchComplete, onError } = options;

  button.addEventListener("click", async () => {
    const offset = Number(button.dataset.offset ?? "0");
    button.disabled = true;
    const originalLabel = button.textContent;
    button.textContent = "Loading…";

    try {
      const response = await fetch(buildUrl(offset), { credentials: "include" });
      if (!response.ok) {
        onError?.(`Could not load more (${response.status}).`);
        button.disabled = false;
        button.textContent = originalLabel;
        return;
      }

      const body = (await response.json()) as PagedEnvelope<T>;

      for (const row of body.items) {
        onRow(row);
      }
      onBatchComplete?.(body.items, body.total);

      const newOffset = offset + body.items.length;
      button.dataset.offset = String(newOffset);
      button.dataset.total = String(body.total);

      if (newOffset >= body.total || body.items.length === 0) {
        button.remove();
      } else {
        button.disabled = false;
        button.textContent = `Load more (${newOffset} of ${body.total})`;
      }
    } catch {
      onError?.("Network error — could not load more. Try again.");
      button.disabled = false;
      button.textContent = originalLabel;
    }
  });
}
```

- [ ] **Step 2: Replace `account.astro`'s local `wireLoadMore`/call sites**

In `frontend/src/pages/account.astro`, inside the `<script>` block (currently starting at line 195):

1. Add near the top of the script block (after the existing `event.preventDefault()` code, before `function formatDate`):
   ```ts
   import { wireLoadMore } from "../lib/loadMore";
   ```
2. Delete the existing local `function wireLoadMore<T>(...)` definition (the one taking `buttonId, listId, pathSuffix, buildItem`).
3. Replace the two call sites at the bottom of the script block:
   ```ts
   function setupLoadMore<T>(
     buttonId: string,
     listId: string,
     pathBase: string,
     buildItem: (row: T) => HTMLLIElement
   ) {
     const button = document.getElementById(buttonId) as HTMLButtonElement | null;
     const list = document.getElementById(listId);
     if (!button || !list) return;

     wireLoadMore<T>({
       button,
       buildUrl: (offset) => `${pathBase}?limit=20&offset=${offset}`,
       onRow: (row) => list.append(buildItem(row)),
     });
   }

   setupLoadMore<FetchedContribution>(
     "contributions-load-more",
     "my-contributions-list",
     "/api/v1/contributions/mine",
     buildContributionItem
   );
   setupLoadMore<FetchedVote>(
     "votes-load-more",
     "my-votes-list",
     "/api/v1/contributions/mine/votes",
     buildVoteItem
   );
   ```

`FetchedContribution`, `FetchedVote`, `buildContributionItem`, `buildVoteItem` are the existing interfaces/functions already in this script block — unchanged.

- [ ] **Step 3: Replace `moderation.astro`'s inline fetch logic in `wireContribLoadMore`**

In `frontend/src/pages/admin/moderation.astro`, inside the `<script>` block (currently starting at line 369):

1. Add an import near the top of the script block (alongside the file's other top-of-script setup, before `function formatDate`):
   ```ts
   import { wireLoadMore } from "../../lib/loadMore";
   ```
2. Replace the body of `wireContribLoadMore()` (currently a hand-rolled `button.addEventListener("click", async () => { ... })`) with:
   ```ts
   function wireContribLoadMore() {
     const button = document.getElementById("contrib-load-more") as HTMLButtonElement | null;
     const list = document.getElementById("contrib-list");
     if (!button || !list) return;

     wireLoadMore<FetchedContribution>({
       button,
       buildUrl: (offset) => `/api/v1/contributions?review_status=pending&limit=20&offset=${offset}`,
       onRow: (item) => {
         const card = buildContributionCard(item);
         list.append(card);
         wireCard(card);
       },
       onBatchComplete: () => updateEmptyState("contrib"),
       onError: (message) => showToast(message, "error"),
     });
   }
   ```

`FetchedContribution`, `buildContributionCard`, `wireCard`, `updateEmptyState`, `showToast` are all pre-existing in this script block — unchanged. This preserves the exact prior behavior: `updateEmptyState("contrib")` still runs once per successful batch (not per row), which is what refreshes the bulk-selection bar's cached count via `bulkRefresh["contrib"]()` — confirmed during the #196 review that this bar re-queries the DOM live on each refresh, so newly-appended cards are picked up correctly.

- [ ] **Step 4: Type-check and build**

Run: `cd frontend && npm run astro check`
Expected: clean (no new errors — only the pre-existing known hint, if any, same as #196's own PR).

Run: `cd frontend && npm run build`
Expected: clean build — this is the step that actually proves the new cross-file `import { wireLoadMore } from "../lib/loadMore"` / `"../../lib/loadMore"` resolves correctly through Astro's client-script bundling (no prior precedent in this codebase for a client-side, non-frontmatter `<script>` importing from `src/lib/` — this build is the real verification, not an assumption).

- [ ] **Step 5: Manual verification via a real local server (no Chromium available, per this project's established convention)**

Run: `cd frontend && node dist/server/entry.mjs` (pointed at the local test-pg-backed backend, same as prior frontend tasks in this project), then in another shell:
```bash
curl -s http://localhost:4321/account | grep -o 'contrib\(utions\)\?-load-more' 
curl -s http://localhost:4321/admin/moderation | grep -o 'contrib-load-more'
```
Expected: both pages still render their "Load more" button markup (SSR unaffected — only the client script changed). Then inspect the compiled client bundle for a request to confirm the shared module was actually bundled in (not tree-shaken away or left as a broken import):
```bash
curl -s http://localhost:4321/account | grep -o '/_astro/[^"]*\.js' | head -5
```
fetch one of the matched `.js` paths and confirm it contains the `wireLoadMore` logic (e.g. `grep -c "Loading…"` on the fetched bundle — both pages' compiled output should each reference this string exactly once now, from the shared module, rather than twice each from duplicated inline code).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/loadMore.ts frontend/src/pages/account.astro frontend/src/pages/admin/moderation.astro
git commit -m "$(cat <<'EOF'
Extract shared "Load more" pagination logic into frontend/src/lib/loadMore.ts

account.astro and admin/moderation.astro each implemented near-identical
fetch/offset/button-label state machines when #196 added pagination to
the three contribution-listing endpoints. Pulled the fetch/paging state
machine into one shared wireLoadMore() helper; each page keeps its own
DOM-building and per-row wiring (moderation.astro's approve/reject/bulk-
selection hooks) via onRow/onBatchComplete callbacks, since that part is
genuinely page-specific.

Fixes #<ISSUE_2>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LEuvh355uWNpbf7hx6sgQc
EOF
)"
```
