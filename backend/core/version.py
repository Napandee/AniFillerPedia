"""Single source of truth for the API version — imported by main.py (for
the FastAPI app metadata / OpenAPI schema) and routers/health.py (for the
/version endpoint) without either importing the other.
"""

API_VERSION = "0.1.0"
