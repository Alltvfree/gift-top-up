-- Two-factor authentication (TOTP, RFC 6238). Secrets are Fernet-encrypted by the API.
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret_enc TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled BOOLEAN NOT NULL DEFAULT false;
-- Highest 30-second time step already accepted: a code can never be used twice.
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_step BIGINT NOT NULL DEFAULT 0;

-- One-time recovery codes for a lost phone (sha256 of a high-entropy code).
CREATE TABLE IF NOT EXISTS user_recovery_codes (
 id BIGSERIAL PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 code_hash TEXT NOT NULL,
 used_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS user_recovery_codes_user_idx ON user_recovery_codes(user_id);

-- Password accepted, waiting for the second factor. Short-lived, limited attempts.
CREATE TABLE IF NOT EXISTS mfa_challenges (
 token_hash TEXT PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 ip INET,
 attempts INTEGER NOT NULL DEFAULT 0,
 expires_at TIMESTAMPTZ NOT NULL
);
