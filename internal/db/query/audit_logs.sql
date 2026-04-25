-- name: CreateAuditLog :exec
INSERT INTO audit_logs (
    organization_id,
    user_id,
    action,
    resource_type,
    resource_id,
    details,
    ip_address
)
VALUES (
    sqlc.narg('organization_id'),
    sqlc.narg('user_id'),
    @action,
    @resource_type,
    sqlc.narg('resource_id'),
    sqlc.narg('details'),
    sqlc.narg('ip_address')
);

-- name: ListAuditLogsByOrg :many
SELECT * FROM audit_logs
WHERE organization_id = @organization_id
ORDER BY created_at DESC
LIMIT  @lim
OFFSET @off;

-- name: ListAuditLogsByOrgAndAction :many
SELECT * FROM audit_logs
WHERE organization_id = @organization_id
  AND action          = @action
ORDER BY created_at DESC
LIMIT  @lim
OFFSET @off;

-- name: ListAuditLogsByResource :many
SELECT * FROM audit_logs
WHERE resource_type = @resource_type
  AND resource_id   = @resource_id
ORDER BY created_at DESC
LIMIT  @lim
OFFSET @off;

-- name: CountAuditLogsByOrg :one
SELECT COUNT(*) FROM audit_logs
WHERE organization_id = @organization_id;
