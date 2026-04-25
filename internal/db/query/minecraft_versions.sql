-- name: UpsertMinecraftVersionWithBuild :one
-- For server types that have build numbers (paper, folia, etc.)
INSERT INTO minecraft_versions (
    server_type,
    version,
    build_number,
    download_url,
    release_date,
    is_stable,
    is_active
)
VALUES (
    @server_type,
    @version,
    @build_number,
    @download_url,
    sqlc.narg('release_date'),
    @is_stable,
    @is_active
)
ON CONFLICT (server_type, version, build_number) WHERE build_number IS NOT NULL
DO UPDATE SET
    download_url = EXCLUDED.download_url,
    release_date = EXCLUDED.release_date,
    is_stable    = EXCLUDED.is_stable,
    is_active    = EXCLUDED.is_active,
    updated_at   = NOW()
RETURNING *;

-- name: UpsertMinecraftVersionNoBuild :one
-- For server types without build numbers (vanilla, spigot, etc.)
INSERT INTO minecraft_versions (
    server_type,
    version,
    download_url,
    release_date,
    is_stable,
    is_active
)
VALUES (
    @server_type,
    @version,
    @download_url,
    sqlc.narg('release_date'),
    @is_stable,
    @is_active
)
ON CONFLICT (server_type, version) WHERE build_number IS NULL
DO UPDATE SET
    download_url = EXCLUDED.download_url,
    release_date = EXCLUDED.release_date,
    is_stable    = EXCLUDED.is_stable,
    is_active    = EXCLUDED.is_active,
    updated_at   = NOW()
RETURNING *;

-- name: GetMinecraftVersionByID :one
SELECT * FROM minecraft_versions WHERE id = @id AND is_active = TRUE;

-- name: GetMinecraftVersionByTypeAndVersion :one
-- Returns the highest build_number for the given server_type and version.
SELECT * FROM minecraft_versions
WHERE server_type = @server_type
  AND version     = @version
  AND is_active   = TRUE
ORDER BY build_number DESC NULLS LAST
LIMIT 1;

-- name: GetMinecraftVersionByTypeVersionBuild :one
SELECT * FROM minecraft_versions
WHERE server_type  = @server_type
  AND version      = @version
  AND build_number = @build_number
  AND is_active    = TRUE;

-- name: ListActiveMinecraftVersions :many
SELECT * FROM minecraft_versions
WHERE is_active = TRUE
ORDER BY server_type ASC, version DESC, build_number DESC NULLS LAST;

-- name: ListActiveMinecraftVersionsByType :many
SELECT * FROM minecraft_versions
WHERE server_type = @server_type
  AND is_active   = TRUE
ORDER BY version DESC, build_number DESC NULLS LAST;

-- name: DeactivateMinecraftVersionsByType :exec
UPDATE minecraft_versions
SET is_active  = FALSE,
    updated_at = NOW()
WHERE server_type = @server_type AND is_active = TRUE;

-- name: GetLatestVersionUpdateLog :one
SELECT * FROM version_update_logs
ORDER BY started_at DESC
LIMIT 1;

-- name: CreateVersionUpdateLog :one
INSERT INTO version_update_logs (trigger, server_types, status, triggered_by_user_id)
VALUES (
    @trigger,
    sqlc.narg('server_types'),
    'running',
    sqlc.narg('triggered_by_user_id')
)
RETURNING *;

-- name: CompleteVersionUpdateLog :exec
UPDATE version_update_logs
SET status               = @status,
    versions_added       = @versions_added,
    versions_updated     = @versions_updated,
    versions_deactivated = @versions_deactivated,
    execution_time_ms    = @execution_time_ms,
    error_message        = sqlc.narg('error_message'),
    completed_at         = NOW()
WHERE id = @id;
