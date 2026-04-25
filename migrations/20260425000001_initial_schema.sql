-- +goose Up

-- ============================================================
-- users
-- ============================================================
CREATE TABLE users (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL,
    username        VARCHAR(50)  NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    deleted_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX users_email_unique
    ON users (email)
    WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX users_username_unique
    ON users (username)
    WHERE deleted_at IS NULL;

CREATE INDEX users_deleted_at_idx ON users (deleted_at);

-- ============================================================
-- refresh_tokens
-- ============================================================
CREATE TABLE refresh_tokens (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash   VARCHAR(64)  NOT NULL,
    user_id      UUID         NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    device_name  VARCHAR(200),
    expires_at   TIMESTAMPTZ  NOT NULL,
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX refresh_tokens_token_hash_unique ON refresh_tokens (token_hash);

CREATE INDEX refresh_tokens_user_id_idx ON refresh_tokens (user_id);

CREATE INDEX refresh_tokens_active_idx
    ON refresh_tokens (user_id, expires_at)
    WHERE revoked_at IS NULL;

-- ============================================================
-- organizations
-- ============================================================
CREATE TABLE organizations (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(100) NOT NULL,
    slug          VARCHAR(50)  NOT NULL,
    owner_user_id UUID         NOT NULL REFERENCES users (id),
    deleted_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX organizations_slug_unique
    ON organizations (slug)
    WHERE deleted_at IS NULL;

CREATE INDEX organizations_owner_user_id_idx ON organizations (owner_user_id);

CREATE INDEX organizations_deleted_at_idx ON organizations (deleted_at);

-- ============================================================
-- organization_members
-- ============================================================
CREATE TABLE organization_members (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations (id),
    user_id             UUID        NOT NULL REFERENCES users (id),
    permissions         JSONB       NOT NULL DEFAULT '[]',
    invited_by_user_id  UUID        REFERENCES users (id) ON DELETE SET NULL,
    joined_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Partial unique: a user cannot be an active member twice
CREATE UNIQUE INDEX organization_members_org_user_unique
    ON organization_members (organization_id, user_id)
    WHERE deleted_at IS NULL;

CREATE INDEX organization_members_organization_id_idx ON organization_members (organization_id);

CREATE INDEX organization_members_user_id_idx ON organization_members (user_id);

CREATE INDEX organization_members_deleted_at_idx ON organization_members (deleted_at);

-- ============================================================
-- minecraft_versions
-- ============================================================
CREATE TYPE server_type_enum AS ENUM (
    'vanilla', 'paper', 'folia', 'spigot', 'purpur', 'forge', 'fabric', 'neoforge'
);

CREATE TABLE minecraft_versions (
    id           UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    server_type  server_type_enum NOT NULL,
    version      VARCHAR(50)      NOT NULL,
    build_number INT,
    download_url TEXT             NOT NULL,
    release_date TIMESTAMPTZ,
    is_stable    BOOLEAN          NOT NULL DEFAULT TRUE,
    is_active    BOOLEAN          NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ      NOT NULL DEFAULT NOW()
);

-- build_number が NULL のサーバータイプ (vanilla 等) と NULL でないタイプ (paper 等) で
-- NULL != NULL となる PostgreSQL の挙動を回避するため partial index を分割する
CREATE UNIQUE INDEX minecraft_versions_type_version_build_unique
    ON minecraft_versions (server_type, version, build_number)
    WHERE build_number IS NOT NULL;

CREATE UNIQUE INDEX minecraft_versions_type_version_no_build_unique
    ON minecraft_versions (server_type, version)
    WHERE build_number IS NULL;

CREATE INDEX minecraft_versions_server_type_idx ON minecraft_versions (server_type);

CREATE INDEX minecraft_versions_is_active_idx
    ON minecraft_versions (server_type, version)
    WHERE is_active = TRUE;

-- ============================================================
-- version_update_logs
-- ============================================================
CREATE TYPE version_update_trigger_enum AS ENUM ('scheduled', 'manual');

CREATE TYPE version_update_status_enum AS ENUM ('running', 'success', 'failed', 'partial');

CREATE TABLE version_update_logs (
    id                   UUID                        PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger              version_update_trigger_enum NOT NULL,
    server_types         JSONB,
    versions_added       INT                         NOT NULL DEFAULT 0,
    versions_updated     INT                         NOT NULL DEFAULT 0,
    versions_deactivated INT                         NOT NULL DEFAULT 0,
    execution_time_ms    INT,
    status               version_update_status_enum  NOT NULL,
    error_message        TEXT,
    triggered_by_user_id UUID                        REFERENCES users (id) ON DELETE SET NULL,
    started_at           TIMESTAMPTZ                 NOT NULL DEFAULT NOW(),
    completed_at         TIMESTAMPTZ
);

CREATE INDEX version_update_logs_started_at_idx ON version_update_logs (started_at DESC);

-- ============================================================
-- servers
-- ============================================================
CREATE TYPE server_status_enum AS ENUM (
    'creating', 'stopped', 'starting', 'running', 'stopping',
    'restarting', 'restoring', 'error', 'deleting', 'deleted'
);

CREATE TYPE runner_type_enum AS ENUM ('host', 'docker', 'podman');

CREATE TABLE servers (
    id                 UUID               PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id    UUID               NOT NULL REFERENCES organizations (id),
    name               VARCHAR(100)       NOT NULL,
    slug               VARCHAR(50)        NOT NULL,
    description        TEXT,
    minecraft_version  VARCHAR(20)        NOT NULL,
    server_type        server_type_enum   NOT NULL,
    status             server_status_enum NOT NULL DEFAULT 'creating',
    runner_type        runner_type_enum   NOT NULL,
    runner_instance_id VARCHAR(255),
    max_memory_mb      INT                NOT NULL DEFAULT 2048,
    max_cpu_cores      FLOAT              NOT NULL DEFAULT 1.0,
    max_disk_gb        INT                NOT NULL DEFAULT 20,
    connection_host    VARCHAR(255),
    connection_port    INT,
    deleted_at         TIMESTAMPTZ,
    created_at         TIMESTAMPTZ        NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ        NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX servers_org_slug_unique
    ON servers (organization_id, slug)
    WHERE deleted_at IS NULL;

CREATE INDEX servers_organization_id_idx ON servers (organization_id);

CREATE INDEX servers_status_idx ON servers (status);

CREATE INDEX servers_deleted_at_idx ON servers (deleted_at);

-- ============================================================
-- jobs
-- ============================================================
CREATE TYPE job_type_enum AS ENUM (
    'server_create', 'server_start', 'server_stop',
    'server_restart', 'server_delete',
    'backup_create', 'backup_restore'
);

CREATE TYPE job_status_enum AS ENUM (
    'queued', 'running', 'succeeded', 'failed', 'cancelled'
);

CREATE TABLE jobs (
    id                   UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id            UUID            NOT NULL REFERENCES servers (id),
    type                 job_type_enum   NOT NULL,
    status               job_status_enum NOT NULL DEFAULT 'queued',
    triggered_by_user_id UUID            REFERENCES users (id) ON DELETE SET NULL,
    payload              JSONB           NOT NULL DEFAULT '{}',
    error_message        TEXT,
    retry_count          INT             NOT NULL DEFAULT 0,
    max_retries          INT             NOT NULL DEFAULT 0,
    started_at           TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX jobs_server_id_idx ON jobs (server_id);

CREATE INDEX jobs_status_idx ON jobs (status);

CREATE INDEX jobs_queued_pickup_idx
    ON jobs (created_at ASC)
    WHERE status = 'queued';

-- ============================================================
-- backups
-- ============================================================
CREATE TYPE backup_type_enum AS ENUM ('manual', 'scheduled', 'pre_restore');

CREATE TYPE backup_status_enum AS ENUM ('creating', 'completed', 'failed');

CREATE TYPE storage_backend_enum AS ENUM ('local', 's3_compatible');

CREATE TABLE backups (
    id                 UUID                 PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id          UUID                 NOT NULL REFERENCES servers (id),
    name               VARCHAR(100)         NOT NULL,
    description        VARCHAR(500),
    backup_type        backup_type_enum     NOT NULL DEFAULT 'manual',
    status             backup_status_enum   NOT NULL DEFAULT 'creating',
    storage_backend    storage_backend_enum NOT NULL,
    storage_key        VARCHAR(1000)        NOT NULL,
    file_size_bytes    BIGINT,
    created_by_user_id UUID                 REFERENCES users (id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ          NOT NULL DEFAULT NOW()
);

CREATE INDEX backups_server_id_idx ON backups (server_id);

CREATE INDEX backups_status_idx ON backups (status);

CREATE INDEX backups_created_at_idx ON backups (created_at DESC);

-- ============================================================
-- backup_schedules
-- ============================================================
CREATE TABLE backup_schedules (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id           UUID         NOT NULL UNIQUE REFERENCES servers (id),
    schedule_expression VARCHAR(100) NOT NULL,
    timezone            VARCHAR(50)  NOT NULL DEFAULT 'UTC',
    max_backups         INT          NOT NULL DEFAULT 10 CHECK (max_backups BETWEEN 1 AND 100),
    enabled             BOOLEAN      NOT NULL DEFAULT TRUE,
    only_when_running   BOOLEAN      NOT NULL DEFAULT TRUE,
    last_backup_at      TIMESTAMPTZ,
    next_backup_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX backup_schedules_enabled_next_idx
    ON backup_schedules (next_backup_at)
    WHERE enabled = TRUE;

-- ============================================================
-- backup_schedule_logs
-- ============================================================
CREATE TYPE backup_schedule_action_enum AS ENUM (
    'created', 'updated', 'deleted', 'executed', 'skipped'
);

CREATE TABLE backup_schedule_logs (
    id                  UUID                        PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id           UUID                        NOT NULL REFERENCES servers (id),
    action              backup_schedule_action_enum NOT NULL,
    reason              VARCHAR(255),
    old_config          JSONB,
    new_config          JSONB,
    executed_by_user_id UUID                        REFERENCES users (id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ                 NOT NULL DEFAULT NOW()
);

CREATE INDEX backup_schedule_logs_server_id_idx ON backup_schedule_logs (server_id);

CREATE INDEX backup_schedule_logs_created_at_idx ON backup_schedule_logs (created_at DESC);

-- ============================================================
-- audit_logs
-- ============================================================
CREATE TABLE audit_logs (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID         REFERENCES organizations (id) ON DELETE SET NULL,
    user_id         UUID         REFERENCES users (id) ON DELETE SET NULL,
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(50)  NOT NULL,
    resource_id     UUID,
    details         JSONB,
    ip_address      VARCHAR(45),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX audit_logs_organization_id_idx ON audit_logs (organization_id);

CREATE INDEX audit_logs_user_id_idx ON audit_logs (user_id);

CREATE INDEX audit_logs_action_idx ON audit_logs (action);

CREATE INDEX audit_logs_created_at_idx ON audit_logs (created_at DESC);

CREATE INDEX audit_logs_resource_idx ON audit_logs (resource_type, resource_id);

-- +goose Down

DROP TABLE IF EXISTS audit_logs;

DROP TABLE IF EXISTS backup_schedule_logs;

DROP TABLE IF EXISTS backup_schedules;

DROP TABLE IF EXISTS backups;

DROP TABLE IF EXISTS jobs;

DROP TABLE IF EXISTS servers;

DROP TABLE IF EXISTS version_update_logs;

DROP TABLE IF EXISTS minecraft_versions;

DROP TABLE IF EXISTS organization_members;

DROP TABLE IF EXISTS organizations;

DROP TABLE IF EXISTS refresh_tokens;

DROP TABLE IF EXISTS users;

DROP TYPE IF EXISTS backup_schedule_action_enum CASCADE;

DROP TYPE IF EXISTS storage_backend_enum CASCADE;

DROP TYPE IF EXISTS backup_status_enum CASCADE;

DROP TYPE IF EXISTS backup_type_enum CASCADE;

DROP TYPE IF EXISTS job_status_enum CASCADE;

DROP TYPE IF EXISTS job_type_enum CASCADE;

DROP TYPE IF EXISTS runner_type_enum CASCADE;

DROP TYPE IF EXISTS server_status_enum CASCADE;

DROP TYPE IF EXISTS version_update_status_enum CASCADE;

DROP TYPE IF EXISTS version_update_trigger_enum CASCADE;

DROP TYPE IF EXISTS server_type_enum CASCADE;
