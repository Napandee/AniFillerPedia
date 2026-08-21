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
<p><em>Last updated 2026-08-21.</em></p>

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
through the provider you choose. We do not collect anything beyond what's
listed above.</p>

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

<h2>Your rights</h2>
<p>You can delete your account and personal data at any time, yourself,
with no approval step: call <code>DELETE /api/v1/users/me</code> while
signed in (or use the account settings page once it exists). This removes
your email, display name, avatar, and linked sign-in identifiers
immediately, per the retention terms above.</p>

<h2>Infrastructure</h2>
<p>This site is served through Cloudflare, which processes standard web
request metadata (including IP addresses) as part of normal operation
(security, DDoS protection, caching) &mdash; the same as any Cloudflare-fronted
site. We don't separately collect or store this data ourselves.</p>

<h2>The dataset itself</h2>
<p>This policy covers your personal account data only. The filler/canon
episode dataset itself &mdash; the actual content of this project &mdash; is
covered by a separate open license, not personal-data rules. See
<a href="https://github.com/Napandee/AniFillerPedia/blob/master/DATA_LICENSE">DATA_LICENSE</a>
for the terms that govern reusing that data.</p>

<h2>Questions</h2>
<p>Open an issue at
<a href="https://github.com/Napandee/AniFillerPedia">github.com/Napandee/AniFillerPedia</a>.</p>
</body>
</html>
"""


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> str:
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
