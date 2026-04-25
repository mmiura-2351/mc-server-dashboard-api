-- name: CreateOrganizationMember :one
INSERT INTO organization_members (organization_id, user_id, permissions, invited_by_user_id)
VALUES (@organization_id, @user_id, @permissions, sqlc.narg('invited_by_user_id'))
RETURNING *;

-- name: GetOrganizationMemberByOrgAndUser :one
SELECT * FROM organization_members
WHERE organization_id = @organization_id
  AND user_id         = @user_id
  AND deleted_at IS NULL;

-- name: GetOrganizationMemberByID :one
SELECT * FROM organization_members
WHERE id = @id AND deleted_at IS NULL;

-- name: ListOrganizationMembers :many
SELECT * FROM organization_members
WHERE organization_id = @organization_id
  AND deleted_at IS NULL
ORDER BY joined_at ASC;

-- name: ListOrganizationsByUser :many
SELECT
    o.id,
    o.name,
    o.slug,
    o.owner_user_id,
    o.created_at,
    o.updated_at,
    om.id          AS member_id,
    om.permissions AS member_permissions,
    om.joined_at   AS member_joined_at
FROM organizations o
JOIN organization_members om
    ON om.organization_id = o.id
   AND om.user_id         = @user_id
   AND om.deleted_at IS NULL
WHERE o.deleted_at IS NULL
ORDER BY om.joined_at ASC;

-- name: UpdateOrganizationMemberPermissions :one
UPDATE organization_members
SET permissions = @permissions,
    updated_at  = NOW()
WHERE id = @id AND deleted_at IS NULL
RETURNING *;

-- name: SoftDeleteOrganizationMember :exec
UPDATE organization_members
SET deleted_at = NOW(),
    updated_at = NOW()
WHERE organization_id = @organization_id
  AND user_id         = @user_id
  AND deleted_at IS NULL;

-- name: CountOrganizationMembers :one
SELECT COUNT(*) FROM organization_members
WHERE organization_id = @organization_id AND deleted_at IS NULL;
