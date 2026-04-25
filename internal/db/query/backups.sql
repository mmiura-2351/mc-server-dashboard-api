-- name: CreateBackup :one
INSERT INTO backups (
    server_id,
    name,
    description,
    backup_type,
    storage_backend,
    storage_key,
    created_by_user_id
)
VALUES (
    @server_id,
    @name,
    sqlc.narg('description'),
    @backup_type,
    @storage_backend,
    @storage_key,
    sqlc.narg('created_by_user_id')
)
RETURNING *;

-- name: GetBackupByID :one
SELECT * FROM backups WHERE id = @id;

-- name: GetBackupByServerAndID :one
SELECT * FROM backups
WHERE id = @id AND server_id = @server_id;

-- name: ListBackupsByServer :many
SELECT * FROM backups
WHERE server_id = @server_id
ORDER BY created_at DESC
LIMIT  @lim
OFFSET @off;

-- name: UpdateBackupCompleted :exec
UPDATE backups
SET status          = 'completed',
    file_size_bytes = @file_size_bytes
WHERE id = @id AND status = 'creating';

-- name: UpdateBackupFailed :exec
UPDATE backups
SET status = 'failed'
WHERE id = @id AND status = 'creating';

-- name: DeleteBackup :exec
DELETE FROM backups WHERE id = @id;

-- name: CountCompletedBackupsByServer :one
SELECT COUNT(*) FROM backups
WHERE server_id = @server_id AND status = 'completed';

-- name: ListOldestCompletedBackupsByServer :many
-- Returns completed backups oldest-first; used for retention policy enforcement.
SELECT * FROM backups
WHERE server_id = @server_id AND status = 'completed'
ORDER BY created_at ASC
LIMIT @lim;
