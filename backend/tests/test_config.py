"""Security review (#89): get_settings() must refuse to start rather than
silently run production with the publicly-known default session secret.
Pure unit tests, no DB needed — but get_settings() is @lru_cache'd, so
each test clears that cache before and after to avoid leaking state
between tests (and from whatever the real environment already set).
"""

import pytest

from core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_refuses_default_secret_in_non_development_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("SESSION_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET_KEY"):
        get_settings()


def test_allows_default_secret_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("SESSION_SECRET_KEY", raising=False)
    settings = get_settings()  # must not raise
    assert settings.session_secret_key == "dev-insecure-change-me"


def test_allows_production_with_a_real_secret_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SESSION_SECRET_KEY", "a-real-randomly-generated-secret")
    settings = get_settings()  # must not raise
    assert settings.session_secret_key == "a-real-randomly-generated-secret"
