-- #221 (implementation of the 2026-09-04 local-auth design spec): adds
-- email+password login as a second, first-class way to authenticate,
-- coexisting with the existing GitHub/Discord OAuth columns rather than
-- replacing them. Additive only — one nullable column, one partial
-- index, no existing row touched.
--
-- password_hash is argon2id (services/auth.py), never a reversible
-- encryption of any kind — hashing is one-way and cannot be undone even
-- if the database and any key were both compromised, which encryption
-- cannot guarantee.
ALTER TABLE users ADD COLUMN password_hash TEXT;

-- Only local (password-having) accounts require a unique email. This
-- must NOT constrain existing OAuth-only rows, which were never
-- guaranteed unique on email (it was profile metadata only, sourced
-- from whichever provider supplied it) and must never break.
CREATE UNIQUE INDEX users_email_unique_when_local
    ON users (email)
    WHERE password_hash IS NOT NULL;
