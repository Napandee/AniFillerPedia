# Admin Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give AniFillerPedia's three existing admin-only pages (moderation queue, user management, traffic analytics) one consistent, discoverable entry point — a role-gated shield icon in the header — instead of scattered plain-text nav links, with a shared tabbed layout across all three.

**Architecture:** A new `AdminLayout.astro` wraps the three existing pages with a role-gated tab strip; none of their own data-fetching/role-check logic changes. `/moderation` moves to `/admin/moderation` (301 redirect kept at the old URL, matching the #116 slug-migration precedent). A new `/admin/index.astro` redirects the shield's click to whichever tab the viewer's role can reach. `Header.astro`'s two plain-text nav links are replaced by one shield icon.

**Tech Stack:** Astro (SSR, `@astrojs/node`), no framework islands — plain inline `<script>` only, matching this codebase's existing convention everywhere.

**Spec:** `docs/superpowers/specs/2026-09-05-admin-portal-design.md`

## Global Constraints

- No backend changes of any kind — this is purely frontend routing/component restructuring.
- No new admin functionality — every existing page's own role-check, redirect, and data-fetching logic must be preserved exactly as-is; only the wrapping chrome changes.
- The tab strip is a UI convenience only, never a security boundary — the backend's own per-endpoint role enforcement is unaffected and unchanged.
- `/moderation` → `/admin/moderation` uses a page-level `Astro.redirect(target, 301)` at the routed page itself (not a Caddy rule), matching the established #116 precedent exactly.
- Role lists, exact as used today: Moderation tab → `["moderator", "admin", "owner"]`; Users and Traffic tabs → `["admin", "owner"]`.
- The admin pages stay English-only (no locale wrapper) — only the shield icon's own `title`/`aria-label` (real header chrome, already in the translated surface per #106) needs a translated string across all 5 locales.
- `astro check` / `astro build` must stay clean throughout.

---

### Task 1: `AdminLayout.astro` — shared tab-strip layout

**Files:**
- Create: `frontend/src/layouts/AdminLayout.astro`

**Interfaces:**
- Consumes: nothing new — reads `Astro.locals.user` the same way every existing admin page already does; wraps the existing `frontend/src/layouts/Layout.astro` (props: `title: string`, `noindex?: boolean`).
- Produces: `AdminLayout` component with props `{ title: string; activeTab: "moderation" | "users" | "traffic" }`, importable as `import AdminLayout from "../../layouts/AdminLayout.astro"` from a page under `frontend/src/pages/admin/`. Tasks 2 and 3 import this.

- [ ] **Step 1: Check the real token names this component needs**

Run: `grep -n "color-border-card\|color-text-muted\|color-accent\|font-body" frontend/src/styles/tokens.css` — confirm these exact token names exist (they're already used by `Header.astro` and `login.astro`); use whatever the real names are if any differ.

- [ ] **Step 2: Write the component**

```astro
---
import Layout from "./Layout.astro";

interface Props {
  title: string;
  activeTab: "moderation" | "users" | "traffic";
}

const { title, activeTab } = Astro.props;

// Mirrors the exact role lists each of the three admin pages already
// enforces independently in their own frontmatter (moderation.astro's
// MODERATOR_ROLES; admin/users.astro's and admin/traffic.astro's own
// ["admin", "owner"] checks) — this is a UI convenience only, never a
// security boundary. The backend's own per-endpoint role check is the
// real enforcement, same as every admin page already assumes.
const role = Astro.locals.user?.role ?? "";

const TABS = [
  { id: "moderation", label: "Moderation", href: "/admin/moderation", roles: ["moderator", "admin", "owner"] },
  { id: "users", label: "Users", href: "/admin/users", roles: ["admin", "owner"] },
  { id: "traffic", label: "Traffic", href: "/admin/traffic", roles: ["admin", "owner"] },
] as const;

const visibleTabs = TABS.filter((tab) => tab.roles.includes(role as typeof tab.roles[number]));
---

<Layout title={title} noindex>
  <nav class="admin-tabs" aria-label="Admin sections">
    {visibleTabs.map((tab) => (
      <a href={tab.href} class:list={["admin-tab", { "admin-tab--active": tab.id === activeTab }]}>
        {tab.label}
      </a>
    ))}
  </nav>
  <slot />
</Layout>

<style>
  .admin-tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 24px;
    border-bottom: 2px solid var(--color-border-card);
  }
  .admin-tab {
    font-family: var(--font-body);
    font-weight: 700;
    font-size: 13px;
    padding: 10px 16px;
    color: var(--color-text-muted);
    text-decoration: none;
    border-bottom: 3px solid transparent;
    margin-bottom: -2px;
  }
  .admin-tab--active {
    color: var(--color-accent);
    border-bottom-color: var(--color-accent);
  }
</style>
```

Adjust the token names in the `<style>` block to match whatever Step 1 confirmed if any differ from the guesses above.

- [ ] **Step 3: Verify it builds**

Run: `cd frontend && npx astro check` — expect 0 errors (this component isn't used by any page yet, so `astro build` alone won't exercise it; `astro check`'s type-checking is the real verification at this step).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/layouts/AdminLayout.astro
git commit -m "Add AdminLayout with role-gated admin tab strip"
```

---

### Task 2: Move `/moderation` to `/admin/moderation`

**Files:**
- Create: `frontend/src/pages/admin/moderation.astro` (moved content)
- Modify: `frontend/src/pages/moderation.astro` (becomes a thin redirect stub)

**Interfaces:**
- Consumes: `AdminLayout` (Task 1).
- Produces: the real `/admin/moderation` route; the old `/moderation` URL 301-redirects to it. Task 5's Header.astro update and Task 6's `HomePage.astro` update both link to the new URL.

- [ ] **Step 1: Read the current, real file in full**

Run: `cat frontend/src/pages/moderation.astro` (or use the Read tool) — read every line. This file may have been touched very recently by an unrelated bug fix (issues #218/#228, fixing a baked-in internal API hostname in its client script) — that fix is unrelated to this task and must be preserved exactly; do not revert or alter any fetch-URL logic while moving this file.

- [ ] **Step 2: Create `frontend/src/pages/admin/moderation.astro` with the exact same content, transformed only as follows**

1. Any relative import path that currently reads `../layouts/Layout.astro`, `../components/...`, `../lib/...`, `../i18n/...`, `../api/...` etc. (one level up from `frontend/src/pages/`) needs one more `../` prepended, since this file now lives one directory deeper (`frontend/src/pages/admin/` instead of `frontend/src/pages/`) — e.g. `../layouts/Layout.astro` becomes `../../layouts/Layout.astro`. Apply this to every such import at the top of the frontmatter.
2. Add one new import: `import AdminLayout from "../../layouts/AdminLayout.astro";` (do not remove the existing `Layout` import if the file also uses `Layout` directly for anything other than the top-level page wrap — check first; the common case is the top-level `<Layout title="..." noindex>...</Layout>` is the only usage, in which case the `Layout` import itself can be removed since `AdminLayout` now handles that internally).
3. Replace the top-level `<Layout title="..." ...>` opening tag with `<AdminLayout title="..." activeTab="moderation">` (keep whatever the existing `title` string value is, drop `noindex` from the call site since `AdminLayout` already passes that through unconditionally) and the matching `</Layout>` closing tag with `</AdminLayout>`.
4. Everything else — frontmatter logic (role-check, redirect-if-unauthenticated, data-fetching), the template content between the layout tags, and every `<script>`/`<style>` block — stays byte-for-byte identical to what Step 1 read.

- [ ] **Step 3: Replace the old file with a redirect stub**

Replace the entire contents of `frontend/src/pages/moderation.astro` with:

```astro
---
// #224/#admin-portal (2026-09-05): this page moved to /admin/moderation
// for URL consistency with the other two admin pages (/admin/users,
// /admin/traffic). Permanent redirect, matching the #116 slug-migration
// precedent — a page-level Astro.redirect at the routed page itself,
// not a Caddy rule, so any bookmarked/external link to the old URL
// still works.
return Astro.redirect("/admin/moderation", 301);
---
```

- [ ] **Step 4: Verify it builds**

Run: `cd frontend && npx astro check && npx astro build` — expect 0 errors.

- [ ] **Step 5: Manual verification against a real backend**

Start a local dev server (`cd frontend && npm run dev`) pointed at a real backend, and as a real moderator/admin/owner session: confirm `/admin/moderation` renders the moderation queue exactly as `/moderation` did before, and confirm a request to the old `/moderation` URL returns a 301 to `/admin/moderation`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/admin/moderation.astro frontend/src/pages/moderation.astro
git commit -m "Move /moderation to /admin/moderation, keep a 301 at the old URL"
```

---

### Task 3: Wrap `/admin/users` and `/admin/traffic` in `AdminLayout`

**Files:**
- Modify: `frontend/src/pages/admin/users.astro`
- Modify: `frontend/src/pages/admin/traffic.astro`

**Interfaces:**
- Consumes: `AdminLayout` (Task 1).
- Produces: both pages render with the same tab strip as `/admin/moderation` (Task 2).

Both pages already live under `frontend/src/pages/admin/`, so no import-path depth change is needed here (unlike Task 2's file move) — only the layout swap.

- [ ] **Step 1: Read both files' current top-level Layout usage**

Run: `grep -n "^import Layout\|<Layout \|</Layout>" frontend/src/pages/admin/users.astro frontend/src/pages/admin/traffic.astro` — confirm the exact current `title`/prop values before editing (they may have shifted slightly since this plan was written).

- [ ] **Step 2: In `frontend/src/pages/admin/users.astro`**

Change the import line:
```
import Layout from "../../layouts/Layout.astro";
```
to:
```
import AdminLayout from "../../layouts/AdminLayout.astro";
```
(remove the `Layout` import entirely if nothing else in the file uses `Layout` directly — check first). Change the opening tag `<Layout title="Manage users — AniFillerPedia" noindex>` to `<AdminLayout title="Manage users — AniFillerPedia" activeTab="users">`, and the matching closing `</Layout>` to `</AdminLayout>`. Leave everything else in the file — frontmatter, template content, scripts, styles — untouched.

- [ ] **Step 3: In `frontend/src/pages/admin/traffic.astro`**

Same transformation: import `AdminLayout` instead of (or alongside, if still needed elsewhere) `Layout`; change the opening tag `<Layout title="Traffic analytics — AniFillerPedia" noindex>` to `<AdminLayout title="Traffic analytics — AniFillerPedia" activeTab="traffic">`, and the matching `</Layout>` to `</AdminLayout>`. Leave everything else untouched.

- [ ] **Step 4: Verify it builds**

Run: `cd frontend && npx astro check && npx astro build` — expect 0 errors.

- [ ] **Step 5: Manual verification**

As a real admin/owner session, confirm both `/admin/users` and `/admin/traffic` render with the tab strip, with the correct tab highlighted as active on each, and that clicking the other tabs actually navigates correctly.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/admin/users.astro frontend/src/pages/admin/traffic.astro
git commit -m "Wrap /admin/users and /admin/traffic in AdminLayout"
```

---

### Task 4: `/admin/index.astro` — redirect-only landing page

**Files:**
- Create: `frontend/src/pages/admin/index.astro`

**Interfaces:**
- Consumes: `Astro.locals.user` (same pattern every other admin page already uses).
- Produces: the shield icon's actual link target (`/admin`). Task 5 links here.

- [ ] **Step 1: Write the page**

```astro
---
// #admin-portal (2026-09-05): the shield icon in Header.astro links
// here. This page renders nothing of its own — it exists only to send
// the viewer to whichever admin tab their role can actually reach,
// so there's no dashboard/overview content to build or maintain.
const user = Astro.locals.user;
if (user && ["moderator", "admin", "owner"].includes(user.role)) {
  const target = user.role === "moderator" ? "/admin/moderation" : "/admin/users";
  return Astro.redirect(target, 302);
}
return Astro.redirect("/", 302);
---
```

A 302 (not 301) here, deliberately — unlike Task 2's permanent `/moderation` → `/admin/moderation` URL change, this redirect's target genuinely depends on the current viewer's role and could point somewhere different for a different visitor, so it must never be cached as permanent.

- [ ] **Step 2: Verify it builds**

Run: `cd frontend && npx astro check && npx astro build` — expect 0 errors.

- [ ] **Step 3: Manual verification**

As a moderator session, confirm `/admin` redirects to `/admin/moderation`. As an admin/owner session, confirm it redirects to `/admin/users`. As a logged-out or contributor-role session, confirm it redirects to `/`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/admin/index.astro
git commit -m "Add /admin redirect-only landing page"
```

---

### Task 5: Shield icon in `Header.astro` + i18n key

**Files:**
- Modify: `frontend/src/components/Header.astro:74-79`
- Modify: `frontend/src/i18n/ui.ts`

**Interfaces:**
- Consumes: `/admin` (Task 4).
- Produces: `nav.adminPortal` i18n key, consumed only by this file.

- [ ] **Step 1: Read the current exact block**

Run: `sed -n '70,82p' frontend/src/components/Header.astro` — confirm the exact current text before editing (line numbers may have shifted since this plan was written).

- [ ] **Step 2: Replace the two role-gated text links with one shield icon**

Change:
```astro
    {user && ["moderator", "admin", "owner"].includes(user.role) && (
      <a href={getRelativeLocaleUrl(locale, "/moderation")}>{t("nav.reviewQueue")}</a>
    )}
    {user && ["admin", "owner"].includes(user.role) && (
      <a href={getRelativeLocaleUrl(locale, "/admin/users")}>{t("nav.manageUsers")}</a>
    )}
```
to:
```astro
    {user && ["moderator", "admin", "owner"].includes(user.role) && (
      <a
        href="/admin"
        class:list={["admin-shield", { "admin-shield--active": Astro.url.pathname.startsWith("/admin") }]}
        title={t("nav.adminPortal")}
        aria-label={t("nav.adminPortal")}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      </a>
    )}
```

`/admin` is deliberately a bare path here (not `getRelativeLocaleUrl(locale, "/admin")`) — matching this same file's own existing precedent for other English-only, non-locale-wrapped routes (`/contribute`, `/needs-research`, `/activity`, immediately above this block), since `/admin` has no locale-prefixed page either.

- [ ] **Step 3: Add matching styles**

Add to the `<style>` block (near the existing `.role`/`.logout-form` rules):

```css
  .admin-shield {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--color-text-muted);
    text-decoration: none;
  }
  .admin-shield--active {
    color: var(--color-accent);
  }
```

- [ ] **Step 4: Add the i18n key to all 5 locale files**

In `frontend/src/i18n/ui.ts`, add `"nav.adminPortal"` immediately after the existing `"nav.manageUsers"` key (do NOT remove `nav.reviewQueue`/`nav.manageUsers` — leave them in place across all 5 locales even though nothing references them after this change, matching this project's own established precedent from #224's Task 8 leaving `nav.logInGithub`/`nav.logInDiscord` in place the same way) in the English source-of-truth object and all 4 other locale objects, with these exact values:

| Locale | Value |
|---|---|
| `en` | `Admin` |
| `es` | `Administración` |
| `hi` | `व्यवस्थापन` |
| `ja` | `管理` |
| `zh-cn` | `管理` |

- [ ] **Step 5: Verify it builds and check(s) pass**

Run: `cd frontend && npx astro check && npx astro build` — expect 0 errors. Then check `frontend/src/i18n/` for an existing i18n key-coverage test (e.g. an `i18n.test.ts`-style check, per #224's Task 8 precedent) and run it if one exists, to confirm the new key exists identically in every locale.

- [ ] **Step 6: Manual verification across role tiers**

As a `contributor`-role session, confirm no shield icon appears. As a `moderator` session, confirm the shield appears and its active-state color kicks in when visiting any `/admin/*` page. As an `admin`/`owner` session, same confirmation.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Header.astro frontend/src/i18n/ui.ts
git commit -m "Replace admin nav text links with a role-gated shield icon"
```

---

### Task 6: Update internal links still pointing at the old `/moderation` URL

**Files:**
- Modify: `frontend/src/components/pages/HomePage.astro`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing consumed by a later task — this is the last task in the plan.

- [ ] **Step 1: Find every remaining internal link to the old URL**

Run: `grep -rn '"/moderation"' frontend/src/ --include="*.astro"` — after Tasks 2 and 5, this should find exactly one remaining hit: `HomePage.astro`'s review-queue teaser link (`Header.astro`'s own link was already updated in Task 5). If it finds any other file, update that one the same way as described in Step 2 below, and note it in your report — the plan's own research (at the time this plan was written) found only `HomePage.astro` and `Header.astro` linking directly to `/moderation`, with everything else being either comments or the page route itself.

- [ ] **Step 2: Update the link**

In `frontend/src/components/pages/HomePage.astro`, change the review-queue teaser's `href={getRelativeLocaleUrl(locale, "/moderation")}` (or equivalent) to `href="/admin/moderation"` (bare path, matching Task 5's own reasoning — this route has no locale-prefixed page). Read the surrounding code first to confirm the exact current expression before editing.

- [ ] **Step 3: Verify it builds**

Run: `cd frontend && npx astro check && npx astro build` — expect 0 errors.

- [ ] **Step 4: Manual verification**

As a moderator/admin/owner session, confirm the homepage's review-queue teaser (if currently visible — check what condition shows it, e.g. only when there's a real pending item) links directly to `/admin/moderation`, not `/moderation`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/pages/HomePage.astro
git commit -m "Update homepage review-queue teaser link to /admin/moderation"
```

---

## Final verification (whole plan)

- [ ] `astro check` and `astro build` both clean.
- [ ] Full role-tier manual pass: a `contributor` sees no shield and gets redirected away from any `/admin/*` URL typed directly; a `moderator` sees the shield, reaching `/admin/moderation` only (with `/admin/users` and `/admin/traffic` still correctly redirecting them away if typed directly — this is the existing per-page role-check, unchanged by this plan); an `admin`/`owner` sees the shield and all three tabs.
- [ ] Old `/moderation` URL still works via its 301 redirect.
- [ ] No remaining internal link points at the old `/moderation` URL.
