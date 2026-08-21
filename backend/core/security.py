"""Signed-token helpers backing the session cookie and the OAuth `state`
parameter, plus API-key generation/hashing for #22's export gate. Session
tokens use itsdangerous — HMAC-signed, tamper-evident, with a built-in
expiry check. No server-side session table (see core/config.py's
session_secret_key docstring for why).
"""

import hashlib
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from core.config import get_settings

SESSION_COOKIE_NAME = "afp_session"
OAUTH_STATE_COOKIE_NAME = "afp_oauth_state"


def _serializer(salt: str) -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.session_secret_key, salt=salt)


def create_session_token(user_id: int) -> str:
    return _serializer("session").dumps({"user_id": user_id})


def verify_session_token(token: str) -> int | None:
    settings = get_settings()
    try:
        data = _serializer("session").loads(
            token, max_age=settings.session_max_age_seconds
        )
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")


def create_oauth_state(*, link_user_id: int | None = None) -> str:
    """Encodes CSRF protection plus, when set, which authenticated user is
    attempting a /settings/link/{provider} call — read back on the
    callback so login and linking share one code path but never get
    confused about which one they're doing.
    """
    return _serializer("oauth-state").dumps({"link_user_id": link_user_id})


def verify_oauth_state(token: str) -> dict | None:
    try:
        # 10 minutes is generous for "redirect to provider and back."
        return _serializer("oauth-state").loads(token, max_age=600)
    except (BadSignature, SignatureExpired):
        return None


def generate_api_key() -> str:
    """A high-entropy random token, not a signed/decodable one — unlike the
    session cookie above, this has no payload to encode, just needs to be
    unguessable. `secrets.token_urlsafe` is the standard choice.
    """
    return f"afp_export_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    """sha256, not bcrypt/argon2: those adaptive hashes exist to slow down
    brute-forcing a *low-entropy* human password. This key already has
    256 bits of entropy from generate_api_key() — a fast hash is fine and
    standard practice for high-entropy API keys (same pattern GitHub/Stripe
    -style tokens use), and lets key lookup stay a simple indexed equality
    query instead of needing to re-derive a slow hash on every /export call.
    """
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
