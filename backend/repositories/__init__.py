# Data-access layer — the only place that writes raw SQL/SQLAlchemy Core
# queries against schema.sql's tables. Services call repositories; routers
# never touch the database directly. Empty scaffolding for now — populated
# as endpoint issues (#7, #8, #12, #13, #14) land; out of scope for #6
# itself.
