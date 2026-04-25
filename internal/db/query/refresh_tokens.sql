-- name: CreateRefreshToken :one
INSERT INTO refresh_tokens (token_hash, user_id, device_name, expires_at)
VALUES (@token_hash, @user_id, sqlc.narg('device_name'), @expires_at)
RETURNING *;

-- name: GetActiveRefreshTokenByHash :one
SELECT * FROM refresh_tokens
WHERE token_hash = @token_hash
  AND revoked_at IS NULL
  AND expires_at > NOW();

-- name: GetRefreshTokenByID :one
SELECT * FROM refresh_tokens WHERE id = @id;

-- name: RevokeRefreshTokenByHash :exec
UPDATE refresh_tokens
SET revoked_at = NOW()
WHERE token_hash = @token_hash AND revoked_at IS NULL;

-- name: RevokeRefreshTokenByID :exec
UPDATE refresh_tokens
SET revoked_at = NOW()
WHERE id = @id AND revoked_at IS NULL;

-- name: RevokeAllUserRefreshTokens :exec
UPDATE refresh_tokens
SET revoked_at = NOW()
WHERE user_id = @user_id AND revoked_at IS NULL;

-- name: UpdateRefreshTokenLastUsed :exec
UPDATE refresh_tokens
SET last_used_at = NOW()
WHERE id = @id;

-- name: ListActiveRefreshTokensByUser :many
SELECT * FROM refresh_tokens
WHERE user_id  = @user_id
  AND revoked_at IS NULL
  AND expires_at > NOW()
ORDER BY created_at DESC;
