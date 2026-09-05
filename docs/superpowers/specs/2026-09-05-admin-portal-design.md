# Admin portal — design spec

Status: approved by Andreas, ready for implementation planning.
Decided: 2026-09-05, via brainstorming session.
Related: split from the same conversation as the local-auth spec
(`2026-09-04-local-auth-design.md`) — local auth shipped first (#224)
since real login was this spec's own prerequisite (nobody could reach
an admin-only page at all until #224 gave AniFillerPedia a working
login path).

## Why

Andreas signed up as owner via #224's local auth and asked for the
admin interface to take inspiration from `Napandee/AniDex`'s own admin
UI — specifically a shield icon in the header corner as the way to
reach admin functions, rather than plain text nav links.

AniFillerPedia's admin-only functionality already exists and works —
`/moderation` (contribution/proposal approval queue), `/admin/users`
(role management, #40), and `/admin/traffic` (#221's analytics
dashboard) — but there's no consistent, discoverable way to reach it:
today it's two plain text links buried in the flat nav bar
("Review queue", "Manage users"), and `/admin/traffic` isn't linked
from the header at all. This spec is about the *entry point and shell*
around already-shipped functionality, not new admin capability.

## Scope

**In scope (v1):**
- A shield icon in `Header.astro`, shown to `moderator`/`admin`/`owner`
  roles, replacing the current plain-text "Review queue"/"Manage
  users" links entirely.
- A shared `AdminLayout.astro` providing consistent chrome (a tab
  strip: Moderation / Users / Traffic) around the three existing admin
  pages — each tab shown only if the current viewer's role can access
  it.
- `/moderation` moves to `/admin/moderation` for URL consistency with
  the other two admin pages, with a 301 redirect stub left at the old
  URL (matching the #116 slug-migration precedent — a page-level
  `Astro.redirect(target, 301)`, not a Caddy rule).
- `/admin/index.astro` — the shield icon's actual link target — a
  redirect-only page sending the viewer to the first tab their role
  can reach (`/admin/moderation` for a moderator, `/admin/users` for
  admin/owner). No content of its own.
- Internal links currently pointing at `/moderation` directly
  (`Header.astro`'s own nav link before this change, `HomePage.astro`'s
  review-queue teaser) updated to the new `/admin/moderation` URL.
- One new i18n key (the shield icon's `title`/`aria-label`) across all
  5 locales, matching #106's established convention.

**Explicitly out of scope (v1) — not oversights:**
- **Any new admin functionality.** Moderation queue logic, user
  role-management logic, and traffic-analytics logic are untouched —
  each existing page keeps its own frontmatter role-check, redirect,
  and data-fetching exactly as it is today. This is purely a
  navigation/chrome layer on top of already-shipped, already-tested
  pages.
- **Any backend change.** No new endpoints, no schema changes — the
  three admin pages already call the API they need.
- **Localizing the admin pages' own content.** `/admin/moderation`,
  `/admin/users`, and `/admin/traffic` stay English-only, matching
  their existing precedent (already cited elsewhere in this codebase
  as "the docs/moderation precedent" for pages with no locale
  wrapper) — only the shield icon itself (real header/nav chrome,
  already in the translated surface per #106) gets a translated
  string.
- **A dashboard/overview page at `/admin`.** The shield's link target
  redirects straight to the first accessible tab rather than rendering
  its own landing content — nothing to build or maintain there.
- **Removing the now-unused `nav.reviewQueue`/`nav.manageUsers` i18n
  keys.** Left in place across all 5 locales, matching this project's
  own established precedent (#224's Task 8 left `nav.logInGithub`/
  `nav.logInDiscord` in place the same way) — a future cleanup pass,
  not this spec's concern.

## Component design

**`frontend/src/layouts/AdminLayout.astro`** (new) — takes the current
viewer's role and active path as inputs, renders a tab strip (three
links: Moderation, Users, Traffic), each shown only if the role list
below includes the viewer's role, then renders `<slot />` for the
wrapped page's own content:

| Tab | Roles that see it | Target |
|---|---|---|
| Moderation | `moderator`, `admin`, `owner` | `/admin/moderation` |
| Users | `admin`, `owner` | `/admin/users` |
| Traffic | `admin`, `owner` | `/admin/traffic` |

Matches the existing role lists already enforced independently by each
page today (`moderation.astro`'s `MODERATOR_ROLES = ["moderator",
"admin", "owner"]`; `admin/users.astro` and `admin/traffic.astro`'s
own `["admin", "owner"]` checks) — the tab strip is a **UI convenience
only**, same explicit caveat `admin/traffic.astro`'s own existing
comment already states for its page-level check: the backend's own
role enforcement is the real security boundary, not this layout.

**`frontend/src/pages/admin/moderation.astro`** (new — moved content
from `frontend/src/pages/moderation.astro`) — the exact same
frontmatter (role-check, redirect, data-fetching) and template content
as today's `moderation.astro`, now wrapped in `AdminLayout`.

**`frontend/src/pages/moderation.astro`** (rewritten) — becomes a thin
redirect stub:
```astro
---
return Astro.redirect("/admin/moderation", 301);
---
```

**`frontend/src/pages/admin/users.astro`** and
**`frontend/src/pages/admin/traffic.astro`** (modified) — each wraps
its existing, untouched content in `AdminLayout` instead of whatever
top-level structure it uses today.

**`frontend/src/pages/admin/index.astro`** (new) — frontmatter-only:
```astro
---
const user = Astro.locals.user;
if (user && ["moderator", "admin", "owner"].includes(user.role)) {
  const target = user.role === "moderator" ? "/admin/moderation" : "/admin/users";
  return Astro.redirect(target, 302);
}
return Astro.redirect("/", 302);
---
```

**`frontend/src/components/Header.astro`** (modified) — the current
`{user && [...].includes(user.role) && <a>...</a>}` blocks for
"Review queue"/"Manage users" (two separate conditionals) are replaced
by one shield-icon link, shown to `["moderator", "admin", "owner"]`,
pointing at `/admin`, with an active-state class applied when
`Astro.url.pathname` starts with `/admin` (covers all three real pages
once `/moderation` has moved) — matching this project's own Playful
Fandom accent (`--color-accent`), not AniDex's purple, for that active
state.

**`frontend/src/components/pages/HomePage.astro`** (modified) — the
existing review-queue teaser link's `href` updated from `/moderation`
to `/admin/moderation` directly (not left to rely on the redirect for
an internal link).

**`frontend/src/i18n/ui.ts`** (modified) — one new key,
`nav.adminPortal`, for the shield icon's `title`/`aria-label`, added to
the English source-of-truth object and all 4 other locale files with
the same key, matching #106's own "every locale gets identical key
coverage" convention.

## Auth / role-gating

No new mechanism. Every page keeps its own existing
`Astro.locals.user` role-check and redirect exactly as it is today —
this spec only adds a shared visual shell and a navigation entry
point. The backend's own per-endpoint role enforcement (already
independent of any frontend check, per this project's own established
defense-in-depth pattern) is unaffected and untouched.

## Testing

Almost entirely frontend/UI, no new backend tests needed (no backend
changes at all):
- `astro check` / `astro build` clean.
- Manual verification against the real backend, across all relevant
  role tiers: a `contributor` sees no shield at all; a `moderator`
  sees the shield and lands on `/admin/moderation` only (Users/Traffic
  tabs absent); an `admin`/`owner` sees the shield and all three tabs.
- Confirm the old `/moderation` URL 301-redirects to
  `/admin/moderation`.
- Confirm `HomePage.astro`'s review-queue teaser link points directly
  at the new URL (no unnecessary redirect hop for an internal link).

## Migration safety

No schema or backend change of any kind — purely frontend routing and
component restructuring. The `/moderation` → `/admin/moderation` move
is additive-safe: the old URL keeps working via the 301 redirect, so
no existing bookmark or external link breaks.

## Open questions

None remaining — every decision point raised during brainstorming
(hub consolidation vs. simple dropdown; shared-layout-over-existing-
routes vs. one true single-page hub; replacing vs. keeping the old nav
links; moderator visibility of the shield; the `/moderation` URL move)
was resolved above. If implementation surfaces something not covered
here, treat it as new scope requiring its own quick decision, not
something to silently improvise.
