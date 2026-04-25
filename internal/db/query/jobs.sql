-- name: CreateJob :one
INSERT INTO jobs (server_id, type, triggered_by_user_id, payload, max_retries)
VALUES (
    @server_id,
    @type,
    sqlc.narg('triggered_by_user_id'),
    @payload,
    @max_retries
)
RETURNING *;

-- name: GetJobByID :one
SELECT * FROM jobs WHERE id = @id;

-- name: GetJobByServerAndID :one
SELECT * FROM jobs
WHERE id = @id AND server_id = @server_id;

-- name: ListJobsByServer :many
SELECT * FROM jobs
WHERE server_id = @server_id
ORDER BY created_at DESC
LIMIT  @lim
OFFSET @off;

-- name: GetNextQueuedJob :one
-- Atomically claim the oldest queued job; skip jobs locked by other workers.
-- Note: per-server serialization (同一サーバーの running ジョブが存在しないことの確認) は
-- ワーカー側の責務。ジョブ取り出し後に CountJobsByServerAndStatus で status='running'
-- を確認し、存在すれば処理を遅延させること。
SELECT * FROM jobs
WHERE status = 'queued'
ORDER BY created_at ASC
LIMIT 1
FOR UPDATE SKIP LOCKED;

-- name: UpdateJobStarted :exec
UPDATE jobs
SET status     = 'running',
    started_at = NOW()
WHERE id = @id AND status = 'queued';

-- name: UpdateJobCompleted :exec
UPDATE jobs
SET status        = @status,
    error_message = sqlc.narg('error_message'),
    completed_at  = NOW()
WHERE id = @id AND status = 'running';

-- name: CancelJob :execrows
UPDATE jobs
SET status       = 'cancelled',
    completed_at = NOW()
WHERE id     = @id
  AND status = 'queued';

-- name: IncrementJobRetryCount :exec
UPDATE jobs
SET retry_count = retry_count + 1
WHERE id = @id;

-- name: CountJobsByServerAndStatus :one
SELECT COUNT(*) FROM jobs
WHERE server_id = @server_id AND status = @status;
