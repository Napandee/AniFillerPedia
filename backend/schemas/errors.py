"""Generic, reusable OpenAPI error-response body.

Most of this API's error cases (404/401/403/400/429...) share the exact
same `{"detail": "<message>"}` shape FastAPI's own `HTTPException`
produces by default. A single shared model here lets every route's
`responses={...}` declaration document that real shape without a
one-off `BaseModel` per status code per route (#138).

A handful of endpoints have a genuinely structured (non-string) `detail`
body instead — those keep their own dedicated model
(schemas/contributions.py's `DuplicatePendingContribution`/
`BulkRangeError`/`BulkSubmissionRateLimited`), not this one.
"""

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    detail: str
