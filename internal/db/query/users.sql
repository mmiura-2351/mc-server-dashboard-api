-- name: CreateUser :one
INSERT INTO users (email, username, hashed_password)
VALUES (@email, @username, @hashed_password)
RETURNING *;

-- name: GetUserByID :one
SELECT * FROM users
WHERE id = @id AND deleted_at IS NULL;

-- name: GetUserByEmail :one
SELECT * FROM users
WHERE email = @email AND deleted_at IS NULL;

-- name: UpdateUser :one
UPDATE users
SET username   = @username,
    email      = @email,
    updated_at = NOW()
WHERE id = @id AND deleted_at IS NULL
RETURNING *;

-- name: UpdateUserPassword :exec
UPDATE users
SET hashed_password = @hashed_password,
    updated_at      = NOW()
WHERE id = @id AND deleted_at IS NULL;

-- name: DeactivateUser :exec
UPDATE users
SET is_active  = FALSE,
    updated_at = NOW()
WHERE id = @id AND deleted_at IS NULL;

-- name: SoftDeleteUser :exec
UPDATE users
SET deleted_at = NOW(),
    updated_at = NOW()
WHERE id = @id AND deleted_at IS NULL;
