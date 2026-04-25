-- name: CreateOrganization :one
INSERT INTO organizations (name, slug, owner_user_id)
VALUES (@name, @slug, @owner_user_id)
RETURNING *;

-- name: GetOrganizationByID :one
SELECT * FROM organizations
WHERE id = @id AND deleted_at IS NULL;

-- name: GetOrganizationBySlug :one
SELECT * FROM organizations
WHERE slug = @slug AND deleted_at IS NULL;

-- name: UpdateOrganization :one
UPDATE organizations
SET name       = @name,
    slug       = @slug,
    updated_at = NOW()
WHERE id = @id AND deleted_at IS NULL
RETURNING *;

-- name: TransferOrganizationOwnership :one
UPDATE organizations
SET owner_user_id = @new_owner_user_id,
    updated_at    = NOW()
WHERE id = @id AND deleted_at IS NULL
RETURNING *;

-- name: SoftDeleteOrganization :exec
UPDATE organizations
SET deleted_at = NOW(),
    updated_at = NOW()
WHERE id = @id AND deleted_at IS NULL;
