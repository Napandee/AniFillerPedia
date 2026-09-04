"""Legal/policy pages served directly by the API — no frontend exists yet
(Phase 5), and Google's OAuth verification review (#24) needs a real,
stable public URL to point at, so this can't wait for one.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from schemas.export import ExportManifest

router = APIRouter(tags=["legal"])

_PRIVACY_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Privacy Policy — AniFillerPedia</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; color: #1a1a1a; }
  h1 { font-size: 1.6rem; } h2 { font-size: 1.15rem; margin-top: 2rem; }
  code { background: #f0f0f0; padding: 0.1rem 0.3rem; border-radius: 3px; }
</style>
</head>
<body>
<h1>Privacy Policy</h1>
<p><em>Last updated 2026-08-22.</em></p>

<p>AniFillerPedia is a community-editable database of anime filler/canon episode
data. You can read every piece of data on this site, and you can submit a
correction, without ever creating an account &mdash; anonymous submissions are
allowed by design. This policy only applies to the small amount of personal
data collected if you choose to sign in.</p>

<h2>What we collect</h2>
<p>If you sign in with GitHub or Discord, the provider gives us:</p>
<ul>
  <li>A unique account ID from that provider</li>
  <li>Your username / display name</li>
  <li>Your avatar image URL</li>
  <li>Your email address, if the provider shares it</li>
</ul>
<p>We never see or store your password &mdash; authentication happens entirely
through the provider you choose.</p>
<p>Separately, if you request an API key for the bulk <code>/export</code>
endpoint, we collect the email address you provide. Unlike your account
data above, this isn't tied to a login and <code>DELETE /api/v1/users/me</code>
doesn't touch it &mdash; see "How long we keep it" below for what applies
to it instead.</p>
<p>Beyond the two paths above, we do not collect anything else.</p>

<h2>Why we collect it</h2>
<p>Solely to attribute your contributions (corrections, citations, series
proposals, votes) to your account, to support the moderation and approval
workflow this project is built around, and to help prevent abuse.</p>

<h2>How long we keep it</h2>
<p>Deleting your account removes your personal data (email, display name,
avatar, linked sign-in identifiers) immediately. Your past contributions and
votes are preserved but anonymized &mdash; they remain part of the public
record and audit trail, which a community-maintained database depends on, but
are no longer linked to your identity. Deleted personal data may persist in
backups for up to 14 days.</p>
<p>The email address behind an <code>/export</code> API key is different:
we keep it because it may serve as evidence that you agreed to the
CC&nbsp;BY-NC-SA non-commercial terms before downloading the full dataset,
which is the entire reason that endpoint asks for it &mdash; not a
relationship with a natural end date the way an account is. We keep it for
as long as the key could plausibly still be in use. You can end that
yourself at any time; see "Your rights" below.</p>

<h2>Your rights</h2>
<p>You can delete your account and personal data at any time, yourself,
with no approval step: call <code>DELETE /api/v1/users/me</code> while
signed in (or use the account settings page once it exists). This removes
your email, display name, avatar, and linked sign-in identifiers
immediately, per the retention terms above.</p>
<p>If you requested an <code>/export</code> API key, you can revoke it and
have the associated email removed at any time yourself, no approval step
either: call <code>POST /api/v1/export/revoke</code> with that key in the
<code>X-API-Key</code> header. The key stops working immediately.</p>

<h2>Infrastructure</h2>
<p>This site is served through Cloudflare, which processes standard web
request metadata (including IP addresses) as part of normal operation
(security, DDoS protection, caching) &mdash; the same as any Cloudflare-fronted
site. We don't separately collect or store this data ourselves.</p>
<p>Series and episode pages display cover art sourced from
<a href="https://anilist.co">AniList</a>'s public API. Those images are
loaded directly by your browser from AniList's own servers, not proxied
through ours &mdash; so AniList receives the same standard request metadata
(including your IP address) that any image host receives when your
browser loads an image from it. We don't send AniList anything about you
beyond that, and we don't receive anything back from AniList about you
either.</p>

<h2>The dataset itself</h2>
<p>This policy covers your personal account data only. The filler/canon
episode dataset itself &mdash; the actual content of this project &mdash; is
covered by a separate open license, not personal-data rules. See
<a href="https://github.com/Napandee/AniFillerPedia/blob/master/DATA_LICENSE">DATA_LICENSE</a>
for the terms that govern reusing that data.</p>
<p>The same license applies to what you contribute: by submitting a
correction or proposing a series, you're agreeing that contribution is
released under CC&nbsp;BY-NC-SA 4.0, same as the rest of the dataset &mdash;
every submission requires ticking that agreement explicitly, it's never
assumed. See <a href="/api/v1/license">GET /license</a> for the current
license text and attribution notice in machine-readable form.</p>

<h2>Questions</h2>
<p>Open an issue at
<a href="https://github.com/Napandee/AniFillerPedia">github.com/Napandee/AniFillerPedia</a>.</p>
</body>
</html>
"""


_TOS_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Terms of Service — AniFillerPedia</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 46rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; color: #1a1a1a; }
  h1 { font-size: 1.6rem; } h2 { font-size: 1.15rem; margin-top: 2rem; }
  code { background: #f0f0f0; padding: 0.1rem 0.3rem; border-radius: 3px; }
</style>
</head>
<body>
<h1>Terms of Service</h1>
<p><em>Last updated 2026-09-04.</em></p>

<p>This page covers using and contributing to AniFillerPedia the service —
account conduct, moderation, and what happens if something goes wrong. It's
separate from two other documents: the
<a href="https://github.com/Napandee/AniFillerPedia/blob/master/DATA_LICENSE">DATA_LICENSE</a>
(the terms covering reuse of the dataset itself) and the
<a href="/api/v1/privacy">privacy policy</a> (what personal data we
collect and why). If you're looking for how to actually submit a
correction or proposal, see
<a href="https://github.com/Napandee/AniFillerPedia/blob/master/CONTRIBUTING.md">CONTRIBUTING.md</a>.</p>

<h2>What this service is</h2>
<p>AniFillerPedia is a community-editable database of anime filler/canon
episode data, free to read and free to contribute to. Reading and
contributing require no account; some actions (voting, bulk submission,
seeing your own history) require signing in with GitHub or Discord. We
provide this as-is, at no cost, with no uptime guarantee &mdash; see
"Disclaimer &amp; liability" below.</p>

<h2>Contributor conduct</h2>
<p>By submitting a correction, series proposal, or synonym suggestion
(anonymously or signed in), you agree to:</p>
<ul>
  <li>Submit content you believe is accurate, backed by a real, checkable
  citation &mdash; not a guess dressed up as a citation.</li>
  <li>Not submit spam, harassment, or content unrelated to anime filler/
  canon data.</li>
  <li>Not attempt to game the trust-weighted voting system (e.g.
  coordinating multiple accounts to endorse each other's submissions) or
  otherwise circumvent the moderation/approval workflow this project is
  built around.</li>
  <li>Not attempt to bypass rate limits, Turnstile verification, or any
  other anti-abuse mechanism.</li>
</ul>
<p>Submitting a contribution also means agreeing to license it under
CC&nbsp;BY-NC-SA 4.0, same as the rest of the dataset &mdash; see
<code>license_accepted</code> in <a href="https://github.com/Napandee/AniFillerPedia/blob/master/CONTRIBUTING.md">CONTRIBUTING.md</a>
for how that's captured per-submission.</p>

<h2>Our rights</h2>
<p>We reserve the right to, at our discretion and without prior notice:</p>
<ul>
  <li>Reject, edit, or remove any contribution, series proposal, or
  synonym suggestion, whether pending or already approved &mdash; the
  normal moderation workflow already covers rejection of pending items;
  this also covers removing something after the fact if it turns out to
  be wrong, abusive, or in breach of these terms.</li>
  <li>Suspend or terminate an account's access to write actions
  (submitting, voting) for a violation of these terms &mdash; see
  "Account suspension" below for how that actually works.</li>
  <li>Change or discontinue any part of the service, including the API,
  at any time. We'll try to give notice for anything that would break
  existing integrations, but can't guarantee it.</li>
</ul>

<h2>Account suspension</h2>
<p>An admin or owner may suspend an account that violates the conduct
expectations above. A suspended account can no longer submit
contributions, series proposals, or synonym suggestions, and can no
longer vote &mdash; but can still read every public page and endpoint,
and still retains full GDPR rights over their own account: viewing
<code>GET /api/v1/users/me</code>, exporting the full bundle via
<code>GET /api/v1/users/me/export</code>, and deleting the account via
<code>DELETE /api/v1/users/me</code> all keep working while suspended.
Suspension is not a way to strip someone's own data rights, only a way to
stop further submissions/votes from an account.</p>
<p>There's no formal appeals process at this project's current size (see
"What this doesn't cover" below) &mdash; if you believe a suspension was
made in error, open an issue on the
<a href="https://github.com/Napandee/AniFillerPedia">GitHub repo</a>.</p>

<h2>Disclaimer &amp; liability</h2>
<p>This is a small, community-maintained, non-commercial project. The
service (the site, the API, the moderation workflow) is provided
"as is," without warranty of any kind, express or implied &mdash; we don't
guarantee it will be available, error-free, or fit for any particular
purpose. To the maximum extent permitted by law, we aren't liable for any
damages arising from your use of, or inability to use, the service.</p>
<p>This is distinct from the <a href="https://github.com/Napandee/AniFillerPedia/blob/master/DATA_LICENSE">DATA_LICENSE</a>'s
own "as is" warranty disclaimer, which covers the accuracy of the
filler/canon <em>data itself</em> &mdash; this section covers the
<em>service</em> that hosts and serves it.</p>

<h2>What this doesn't cover</h2>
<p>A full moderation-appeals process, arbitration terms, or jurisdiction-
specific legal boilerplate &mdash; not needed for a project at this size
today. This document, like the rest of this project's legal text, is a
considered good-faith position, not lawyer-reviewed legal advice (same
honesty flag as <a href="/api/v1/license">GET /license</a> and the
privacy policy carry).</p>

<h2>Changes to these terms</h2>
<p>We may update this page as the project grows. Material changes will be
reflected in the "Last updated" date above; check
<a href="https://github.com/Napandee/AniFillerPedia/commits/master/backend/routers/legal.py">this file's
own git history</a> for the exact diff of any change.</p>

<h2>Questions</h2>
<p>Open an issue at
<a href="https://github.com/Napandee/AniFillerPedia">github.com/Napandee/AniFillerPedia</a>.</p>
</body>
</html>
"""


@router.get("/tos", response_class=HTMLResponse)
async def terms_of_service() -> str:
    """#209: Terms of Service / acceptable-use policy, served as static
    HTML directly by the API (no frontend page to hand-copy the prose
    into), same pattern as `GET /privacy` above. Covers contributor
    conduct, our right to remove content/reject contributions/terminate
    access, the account-suspension mechanism (routers/admin.py's
    PATCH /admin/users/{id}/suspension), and a service-level liability
    disclaimer distinct from DATA_LICENSE's own data-only one.
    """
    return _TOS_HTML


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> str:
    """The project's privacy policy, served as static HTML directly by the
    API (no frontend page for it) — also the stable public URL Google's
    OAuth verification review (#24) needs to point at.
    """
    return _PRIVACY_HTML


@router.get("/license", response_model=ExportManifest)
async def license_info() -> ExportManifest:
    """#21's dedicated attribution endpoint — was decided but never
    actually built until now (found while writing #16's API docs).
    Reuses ExportManifest as-is: the bulk export payload (#22) and this
    endpoint describe the exact same license/attribution facts, so one
    model backs both rather than maintaining the text twice.
    """
    return ExportManifest()
