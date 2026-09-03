"""Points the real-dependency integration tests at production by default,
matching backend/tests/test_anilist_sync.py's own "test against the real
thing" convention (see test_server_integration.py's own header comment
for the full reasoning). `setdefault` rather than an unconditional
`setenv`, so a developer iterating locally against
`backend/`+local test-pg can still override `AFP_API_BASE_URL` themselves
before running pytest.
"""

import os

os.environ.setdefault("AFP_API_BASE_URL", "https://anifillerpedia.wiki/api/v1")
