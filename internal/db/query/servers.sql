-- name: CreateServer :one
INSERT INTO servers (
    organization_id,
    name,
    slug,
    description,
    minecraft_version,
    server_type,
    runner_type,
    max_memory_mb,
    max_cpu_cores,
    max_disk_gb
)
VALUES (
    @organization_id,
    @name,
    @slug,
    sqlc.narg('description'),
    @minecraft_version,
    @server_type,
    @runner_type,
    @max_memory_mb,
    @max_cpu_cores,
    @max_disk_gb
)
RETURNING *;

-- name: GetServerByID :one
SELECT * FROM servers
WHERE id = @id AND deleted_at IS NULL;

-- name: GetServerByOrgAndID :one
SELECT * FROM servers
WHERE id              = @id
  AND organization_id = @organization_id
  AND deleted_at IS NULL;

-- name: GetServerByOrgAndSlug :one
SELECT * FROM servers
WHERE organization_id = @organization_id
  AND slug            = @slug
  AND deleted_at IS NULL;

-- name: ListServersByOrg :many
SELECT * FROM servers
WHERE organization_id = @organization_id
  AND deleted_at IS NULL
ORDER BY created_at DESC;

-- name: UpdateServerMetadata :one
UPDATE servers
SET name        = @name,
    description = sqlc.narg('description'),
    updated_at  = NOW()
WHERE id = @id AND deleted_at IS NULL
RETURNING *;

-- name: UpdateServerSettings :one
UPDATE servers
SET max_memory_mb = @max_memory_mb,
    max_cpu_cores = @max_cpu_cores,
    max_disk_gb   = @max_disk_gb,
    updated_at    = NOW()
WHERE id = @id AND deleted_at IS NULL
RETURNING *;

-- name: UpdateServerStatus :exec
UPDATE servers
SET status     = @status,
    updated_at = NOW()
WHERE id = @id;

-- name: UpdateServerRunnerInstance :exec
UPDATE servers
SET runner_instance_id = @runner_instance_id,
    updated_at         = NOW()
WHERE id = @id;

-- name: UpdateServerConnectionInfo :exec
UPDATE servers
SET connection_host = sqlc.narg('connection_host'),
    connection_port = sqlc.narg('connection_port'),
    updated_at      = NOW()
WHERE id = @id;

-- name: SoftDeleteServer :exec
UPDATE servers
SET deleted_at = NOW(),
    updated_at = NOW()
WHERE id = @id AND deleted_at IS NULL;
