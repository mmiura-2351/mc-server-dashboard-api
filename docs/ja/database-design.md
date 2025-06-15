# データベース設計 - Minecraft Server Dashboard API V2

## 概要

この文書は、Minecraft Server Dashboard API V2のための包括的なデータベース設計を提供します。PostgreSQL（本番環境）とSQLite（開発環境）の両方に対応したスキーマ定義、リレーションシップ、インデックス、最適化戦略が含まれています。

## データベースアーキテクチャ

### 技術スタック
- **プライマリデータベース**: PostgreSQL 15+（本番環境）
- **開発データベース**: SQLite 3.40+（開発環境）
- **ORM**: SQLAlchemy 2.0（非同期サポート付き）
- **マイグレーション**: Alembic
- **コネクションプーリング**: SQLAlchemy非同期エンジンとコネクションプーリング

### 設計原則
1. **ACID準拠**: 適切な分離レベルによる完全なトランザクションサポート
2. **正規化**: パフォーマンスのための選択的非正規化を伴う第3正規形
3. **イベントソーシング**: 監査と再現のための追記専用イベントログ
4. **CQRSサポート**: マテリアライズドビューによる読み取り/書き込みモデルの分離
5. **スケーラビリティ**: 適切なインデックスによる水平スケーリング設計

## コアスキーマ設計

### 1. ユーザードメイン

#### ユーザーテーブル
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    is_active BOOLEAN DEFAULT true,
    is_approved BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    version INTEGER DEFAULT 1,
    
    CONSTRAINT users_role_check CHECK (role IN ('user', 'operator', 'admin')),
    CONSTRAINT users_username_length CHECK (length(username) >= 3),
    CONSTRAINT users_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

-- インデックス
CREATE INDEX idx_users_active_approved ON users(id) WHERE is_active = true AND is_approved = true;
CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_created_at ON users(created_at);
CREATE INDEX idx_users_email_lower ON users(lower(email));
CREATE INDEX idx_users_username_lower ON users(lower(username));
```

#### ユーザーセッションテーブル
```sql
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_token_hash VARCHAR(255) NOT NULL,
    ip_address INET,
    user_agent TEXT,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_used_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_revoked BOOLEAN DEFAULT false,
    
    CONSTRAINT sessions_expires_future CHECK (expires_at > created_at)
);

-- インデックス
CREATE INDEX idx_sessions_user_active ON user_sessions(user_id) WHERE is_revoked = false;
CREATE INDEX idx_sessions_expires ON user_sessions(expires_at);
CREATE INDEX idx_sessions_token_hash ON user_sessions(refresh_token_hash);
```

### 2. サーバードメイン

#### サーバーテーブル
```sql
CREATE TABLE servers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    port INTEGER UNIQUE NOT NULL,
    status VARCHAR(20) DEFAULT 'stopped',
    minecraft_version VARCHAR(20) NOT NULL,
    server_type VARCHAR(20) DEFAULT 'vanilla',
    memory_mb INTEGER NOT NULL,
    java_args TEXT,
    auto_start BOOLEAN DEFAULT false,
    auto_restart BOOLEAN DEFAULT false,
    process_id INTEGER,
    last_started_at TIMESTAMP WITH TIME ZONE,
    last_stopped_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    version INTEGER DEFAULT 1,
    
    CONSTRAINT servers_port_range CHECK (port BETWEEN 1024 AND 65535),
    CONSTRAINT servers_memory_range CHECK (memory_mb BETWEEN 512 AND 32768),
    CONSTRAINT servers_status_check CHECK (status IN ('stopped', 'starting', 'running', 'stopping', 'crashed')),
    CONSTRAINT servers_type_check CHECK (server_type IN ('vanilla', 'paper', 'spigot', 'forge', 'fabric', 'modded')),
    CONSTRAINT servers_name_owner_unique UNIQUE (name, owner_id)
);

-- インデックス
CREATE INDEX idx_servers_owner_status ON servers(owner_id, status);
CREATE INDEX idx_servers_port ON servers(port);
CREATE INDEX idx_servers_status ON servers(status);
CREATE INDEX idx_servers_type ON servers(server_type);
CREATE INDEX idx_servers_created_at ON servers(created_at);
CREATE INDEX idx_servers_version ON servers(minecraft_version);
```

#### サーバー設定テーブル
```sql
CREATE TABLE server_configurations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    configuration_type VARCHAR(50) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by UUID REFERENCES users(id),
    
    CONSTRAINT config_type_check CHECK (configuration_type IN ('server_properties', 'bukkit_yml', 'spigot_yml', 'paper_yml', 'ops_json', 'whitelist_json')),
    CONSTRAINT server_config_unique UNIQUE (server_id, configuration_type, file_name)
);

-- インデックス
CREATE INDEX idx_server_configs_server ON server_configurations(server_id);
CREATE INDEX idx_server_configs_type ON server_configurations(configuration_type);
CREATE INDEX idx_server_configs_active ON server_configurations(server_id, is_active);
```

### 3. グループドメイン

#### グループテーブル
```sql
CREATE TABLE groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    group_type VARCHAR(20) NOT NULL,
    owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    is_public BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    version INTEGER DEFAULT 1,
    
    CONSTRAINT groups_type_check CHECK (group_type IN ('op', 'whitelist', 'blacklist')),
    CONSTRAINT groups_name_owner_unique UNIQUE (name, owner_id)
);

-- インデックス
CREATE INDEX idx_groups_owner_type ON groups(owner_id, group_type);
CREATE INDEX idx_groups_public ON groups(is_public) WHERE is_public = true;
CREATE INDEX idx_groups_created_at ON groups(created_at);
```

#### プレイヤーテーブル
```sql
CREATE TABLE players (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    minecraft_uuid UUID UNIQUE NOT NULL,
    username VARCHAR(16) NOT NULL,
    display_name VARCHAR(16),
    last_seen TIMESTAMP WITH TIME ZONE,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_online BOOLEAN DEFAULT false,
    skin_url TEXT,
    cape_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE,
    
    CONSTRAINT players_username_length CHECK (length(username) BETWEEN 3 AND 16),
    CONSTRAINT players_username_pattern CHECK (username ~* '^[a-zA-Z0-9_]+$')
);

-- インデックス
CREATE INDEX idx_players_uuid ON players(minecraft_uuid);
CREATE INDEX idx_players_username_lower ON players(lower(username));
CREATE INDEX idx_players_online ON players(is_online) WHERE is_online = true;
CREATE INDEX idx_players_last_seen ON players(last_seen);
```

#### グループプレイヤー結合テーブル
```sql
CREATE TABLE group_players (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    player_id UUID NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    added_by UUID REFERENCES users(id),
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true,
    
    CONSTRAINT group_players_unique UNIQUE (group_id, player_id)
);

-- インデックス
CREATE INDEX idx_group_players_group ON group_players(group_id);
CREATE INDEX idx_group_players_player ON group_players(player_id);
CREATE INDEX idx_group_players_active ON group_players(group_id, is_active);
```

#### サーバーグループ結合テーブル
```sql
CREATE TABLE server_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    priority INTEGER DEFAULT 0,
    attached_by UUID REFERENCES users(id),
    attached_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true,
    
    CONSTRAINT server_groups_unique UNIQUE (server_id, group_id)
);

-- インデックス
CREATE INDEX idx_server_groups_server ON server_groups(server_id);
CREATE INDEX idx_server_groups_group ON server_groups(group_id);
CREATE INDEX idx_server_groups_priority ON server_groups(server_id, priority);
CREATE INDEX idx_server_groups_active ON server_groups(server_id, is_active);
```

### 4. バックアップドメイン

#### バックアップテーブル
```sql
CREATE TABLE backups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    file_path VARCHAR(1000) NOT NULL,
    file_size_bytes BIGINT,
    compression_ratio DECIMAL(5,2),
    backup_type VARCHAR(20) DEFAULT 'manual',
    status VARCHAR(20) DEFAULT 'pending',
    world_name VARCHAR(100),
    minecraft_version VARCHAR(20),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    
    CONSTRAINT backups_type_check CHECK (backup_type IN ('manual', 'scheduled', 'automatic')),
    CONSTRAINT backups_status_check CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    CONSTRAINT backups_size_positive CHECK (file_size_bytes > 0),
    CONSTRAINT backups_server_name_unique UNIQUE (server_id, name)
);

-- インデックス
CREATE INDEX idx_backups_server_created ON backups(server_id, created_at DESC);
CREATE INDEX idx_backups_type ON backups(backup_type);
CREATE INDEX idx_backups_status ON backups(status);
CREATE INDEX idx_backups_completed ON backups(completed_at DESC);
CREATE INDEX idx_backups_size ON backups(file_size_bytes);
```

#### バックアップスケジュールテーブル
```sql
CREATE TABLE backup_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    cron_expression VARCHAR(100) NOT NULL,
    timezone VARCHAR(50) DEFAULT 'UTC',
    retention_count INTEGER DEFAULT 10,
    retention_days INTEGER DEFAULT 30,
    is_active BOOLEAN DEFAULT true,
    only_if_players_online BOOLEAN DEFAULT false,
    compress_backup BOOLEAN DEFAULT true,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    last_backup_id UUID REFERENCES backups(id),
    
    CONSTRAINT schedule_retention_positive CHECK (retention_count > 0 AND retention_days > 0),
    CONSTRAINT schedule_server_name_unique UNIQUE (server_id, name)
);

-- インデックス
CREATE INDEX idx_backup_schedules_server ON backup_schedules(server_id);
CREATE INDEX idx_backup_schedules_active ON backup_schedules(is_active, next_run_at) WHERE is_active = true;
CREATE INDEX idx_backup_schedules_next_run ON backup_schedules(next_run_at);
```

### 5. ファイルドメイン

#### ファイル履歴テーブル
```sql
CREATE TABLE file_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    file_path VARCHAR(1000) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    mime_type VARCHAR(100),
    encoding VARCHAR(20) DEFAULT 'utf-8',
    change_type VARCHAR(20) NOT NULL,
    content_preview TEXT,
    previous_version_id UUID REFERENCES file_history(id),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT file_change_type_check CHECK (change_type IN ('created', 'modified', 'deleted', 'renamed')),
    CONSTRAINT file_size_positive CHECK (file_size_bytes >= 0)
);

-- インデックス
CREATE INDEX idx_file_history_server_path ON file_history(server_id, file_path);
CREATE INDEX idx_file_history_server_created ON file_history(server_id, created_at DESC);
CREATE INDEX idx_file_history_hash ON file_history(content_hash);
CREATE INDEX idx_file_history_type ON file_history(change_type);
```

### 6. 監視ドメイン

#### サーバーメトリクステーブル
```sql
CREATE TABLE server_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    server_id UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    metric_type VARCHAR(50) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    value DECIMAL(15,4) NOT NULL,
    unit VARCHAR(20),
    tags JSONB DEFAULT '{}',
    
    CONSTRAINT metrics_type_check CHECK (metric_type IN ('cpu_usage', 'memory_usage', 'disk_usage', 'network_in', 'network_out', 'player_count', 'tps', 'latency'))
);

-- インデックス（時系列最適化を使用）
CREATE INDEX idx_server_metrics_server_time ON server_metrics(server_id, timestamp DESC);
CREATE INDEX idx_server_metrics_type_time ON server_metrics(metric_type, timestamp DESC);
CREATE INDEX idx_server_metrics_timestamp ON server_metrics(timestamp DESC);

-- 大容量データセット用の月次パーティショニング
CREATE TABLE server_metrics_y2024m01 PARTITION OF server_metrics
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
```

#### 監査ログテーブル
```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    correlation_id UUID,
    user_id UUID REFERENCES users(id),
    session_id UUID REFERENCES user_sessions(id),
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(50),
    resource_id UUID,
    details JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    request_path VARCHAR(500),
    request_method VARCHAR(10),
    response_status INTEGER,
    execution_time_ms INTEGER,
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT audit_response_status_range CHECK (response_status BETWEEN 100 AND 599)
);

-- インデックス
CREATE INDEX idx_audit_logs_user_time ON audit_logs(user_id, occurred_at DESC);
CREATE INDEX idx_audit_logs_action ON audit_logs(action);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX idx_audit_logs_correlation ON audit_logs(correlation_id);
CREATE INDEX idx_audit_logs_time ON audit_logs(occurred_at DESC);
```

### 7. イベントソーシング

#### ドメインイベントテーブル
```sql
CREATE TABLE domain_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID UNIQUE NOT NULL,
    aggregate_type VARCHAR(50) NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_version INTEGER NOT NULL,
    event_data JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    correlation_id UUID,
    causation_id UUID,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE,
    failed_at TIMESTAMP WITH TIME ZONE,
    retry_count INTEGER DEFAULT 0,
    
    CONSTRAINT events_version_positive CHECK (event_version > 0),
    CONSTRAINT events_retry_count_positive CHECK (retry_count >= 0)
);

-- インデックス
CREATE INDEX idx_domain_events_aggregate ON domain_events(aggregate_type, aggregate_id, event_version);
CREATE INDEX idx_domain_events_type ON domain_events(event_type);
CREATE INDEX idx_domain_events_occurred ON domain_events(occurred_at DESC);
CREATE INDEX idx_domain_events_unprocessed ON domain_events(processed_at) WHERE processed_at IS NULL;
CREATE INDEX idx_domain_events_correlation ON domain_events(correlation_id);
```

## 読み取りモデル（CQRS）

### クエリ最適化用マテリアライズドビュー

#### サーバーリストビュー
```sql
CREATE MATERIALIZED VIEW server_list_view AS
SELECT 
    s.id,
    s.name,
    s.description,
    s.status,
    s.port,
    s.minecraft_version,
    s.server_type,
    s.memory_mb,
    s.created_at,
    s.last_started_at,
    u.username as owner_username,
    u.full_name as owner_full_name,
    COUNT(DISTINCT b.id) as backup_count,
    MAX(b.created_at) as latest_backup_at,
    COUNT(DISTINCT sg.group_id) as attached_groups_count,
    COALESCE(
        (SELECT COUNT(*) FROM group_players gp 
         JOIN server_groups sg2 ON gp.group_id = sg2.group_id 
         WHERE sg2.server_id = s.id AND sg2.is_active = true AND gp.is_active = true),
        0
    ) as total_players
FROM servers s
LEFT JOIN users u ON s.owner_id = u.id
LEFT JOIN backups b ON s.id = b.server_id AND b.status = 'completed'
LEFT JOIN server_groups sg ON s.id = sg.server_id AND sg.is_active = true
GROUP BY s.id, s.name, s.description, s.status, s.port, s.minecraft_version, 
         s.server_type, s.memory_mb, s.created_at, s.last_started_at,
         u.username, u.full_name;

-- マテリアライズドビュー用インデックス
CREATE UNIQUE INDEX idx_server_list_view_id ON server_list_view(id);
CREATE INDEX idx_server_list_view_owner ON server_list_view(owner_username);
CREATE INDEX idx_server_list_view_status ON server_list_view(status);
CREATE INDEX idx_server_list_view_type ON server_list_view(server_type);
```

#### グループサマリービュー
```sql
CREATE MATERIALIZED VIEW group_summary_view AS
SELECT 
    g.id,
    g.name,
    g.description,
    g.group_type,
    g.is_public,
    g.created_at,
    u.username as owner_username,
    COUNT(DISTINCT gp.player_id) as player_count,
    COUNT(DISTINCT sg.server_id) as server_count,
    ARRAY_AGG(DISTINCT p.username ORDER BY p.username) FILTER (WHERE p.username IS NOT NULL) as player_usernames
FROM groups g
LEFT JOIN users u ON g.owner_id = u.id
LEFT JOIN group_players gp ON g.id = gp.group_id AND gp.is_active = true
LEFT JOIN server_groups sg ON g.id = sg.group_id AND sg.is_active = true
LEFT JOIN players p ON gp.player_id = p.id
GROUP BY g.id, g.name, g.description, g.group_type, g.is_public, g.created_at, u.username;

-- インデックス
CREATE UNIQUE INDEX idx_group_summary_view_id ON group_summary_view(id);
CREATE INDEX idx_group_summary_view_owner ON group_summary_view(owner_username);
CREATE INDEX idx_group_summary_view_type ON group_summary_view(group_type);
```

#### バックアップサマリービュー
```sql
CREATE MATERIALIZED VIEW backup_summary_view AS
SELECT 
    s.id as server_id,
    s.name as server_name,
    s.owner_id,
    COUNT(b.id) as total_backups,
    COALESCE(SUM(b.file_size_bytes), 0) as total_size_bytes,
    MAX(b.created_at) as latest_backup_at,
    MIN(b.created_at) as oldest_backup_at,
    COUNT(CASE WHEN b.status = 'completed' THEN 1 END) as successful_backups,
    COUNT(CASE WHEN b.status = 'failed' THEN 1 END) as failed_backups,
    ROUND(
        COUNT(CASE WHEN b.status = 'completed' THEN 1 END)::DECIMAL / 
        GREATEST(COUNT(b.id), 1) * 100, 2
    ) as success_rate
FROM servers s
LEFT JOIN backups b ON s.id = b.server_id
GROUP BY s.id, s.name, s.owner_id;

-- インデックス
CREATE UNIQUE INDEX idx_backup_summary_view_server ON backup_summary_view(server_id);
CREATE INDEX idx_backup_summary_view_owner ON backup_summary_view(owner_id);
```

## データベース関数とトリガー

### 自動タイムスタンプ更新
```sql
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- updated_atカラムを持つすべてのテーブルに適用
CREATE TRIGGER trigger_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_servers_updated_at
    BEFORE UPDATE ON servers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 他のテーブルでも継続...
```


### サーバーステータス検証
```sql
CREATE OR REPLACE FUNCTION validate_server_status_transition()
RETURNS TRIGGER AS $$
BEGIN
    -- ステータス遷移を検証
    IF OLD.status IS NOT NULL AND OLD.status != NEW.status THEN
        CASE 
            WHEN OLD.status = 'stopped' AND NEW.status NOT IN ('starting') THEN
                RAISE EXCEPTION '% から % への無効なステータス遷移', OLD.status, NEW.status;
            WHEN OLD.status = 'starting' AND NEW.status NOT IN ('running', 'crashed', 'stopped') THEN
                RAISE EXCEPTION '% から % への無効なステータス遷移', OLD.status, NEW.status;
            WHEN OLD.status = 'running' AND NEW.status NOT IN ('stopping', 'crashed') THEN
                RAISE EXCEPTION '% から % への無効なステータス遷移', OLD.status, NEW.status;
            WHEN OLD.status = 'stopping' AND NEW.status NOT IN ('stopped', 'crashed') THEN
                RAISE EXCEPTION '% から % への無効なステータス遷移', OLD.status, NEW.status;
        END CASE;
    END IF;
    
    -- ステータスに基づくタイムスタンプ更新
    CASE NEW.status
        WHEN 'running' THEN
            NEW.last_started_at = NOW();
        WHEN 'stopped' THEN
            NEW.last_stopped_at = NOW();
            NEW.process_id = NULL;
    END CASE;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_server_status_validation
    BEFORE UPDATE ON servers
    FOR EACH ROW EXECUTE FUNCTION validate_server_status_transition();
```

## パフォーマンス最適化

### コネクションプーリング設定
```python
# SQLAlchemyエンジン設定
DATABASE_CONFIG = {
    "pool_size": 20,
    "max_overflow": 30,
    "pool_timeout": 30,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
    "connect_args": {
        "command_timeout": 60,
        "server_settings": {
            "application_name": "mcapi_v2",
            "jit": "off"  # より高速な接続のためJIT無効
        }
    }
}
```

### クエリ最適化戦略

#### 1. プリペアドステートメント
```sql
-- 頻繁に実行されるクエリにはプリペアドステートメントを使用
PREPARE get_user_servers(UUID) AS
    SELECT s.*, u.username as owner_username
    FROM servers s
    JOIN users u ON s.owner_id = u.id
    WHERE s.owner_id = $1
    ORDER BY s.created_at DESC;
```

#### 2. 部分インデックス
```sql
-- アクティブで削除されていないレコードのみインデックス
CREATE INDEX idx_servers_active ON servers(owner_id, status) 
    WHERE status != 'deleted';

CREATE INDEX idx_backups_recent ON backups(server_id, created_at DESC) 
    WHERE created_at > NOW() - INTERVAL '1 year';
```

#### 3. 複合インデックス
```sql
-- 一般的なクエリパターン用の複数カラムインデックス
CREATE INDEX idx_servers_owner_status_created ON servers(owner_id, status, created_at DESC);
CREATE INDEX idx_backups_server_status_created ON backups(server_id, status, created_at DESC);
CREATE INDEX idx_events_aggregate_version ON domain_events(aggregate_type, aggregate_id, event_version);
```

### データベース監視

#### パフォーマンス監視ビュー
```sql
-- 低速クエリ監視
CREATE VIEW slow_queries AS
SELECT 
    query,
    calls,
    total_time,
    mean_time,
    rows
FROM pg_stat_statements
WHERE mean_time > 100  -- 平均100ms以上のクエリ
ORDER BY mean_time DESC;

-- インデックス使用状況監視
CREATE VIEW unused_indexes AS
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE idx_scan = 0
ORDER BY schemaname, tablename;
```

## 移行戦略

### Alembicマイグレーションテンプレート

#### 初期マイグレーション
```python
"""初期データベーススキーマ

Revision ID: 001_initial_schema
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# リビジョン識別子
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # 拡張を作成
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_stat_statements"')
    
    # ユーザーテーブルを作成
    op.create_table('users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('username', sa.VARCHAR(length=50), nullable=False),
        sa.Column('email', sa.VARCHAR(length=255), nullable=False),
        # ... その他のカラム
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('email')
    )
    
    # 他のテーブルで継続...

def downgrade():
    op.drop_table('users')
    # 他のテーブルを逆順で削除...
```

### V1からのデータ移行

#### 移行スクリプトテンプレート
```python
# scripts/migrate_from_v1.py
import asyncio
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine

async def migrate_users():
    """V1からV2にユーザーを移行する。"""
    # 両方のデータベースに接続
    v1_engine = create_async_engine("sqlite:///./app.db")  # V1データベース
    v2_engine = create_async_engine("postgresql://...")   # V2データベース
    
    async with v1_engine.connect() as v1_conn:
        async with v2_engine.connect() as v2_conn:
            # V1から読み取り
            result = await v1_conn.execute("SELECT * FROM users")
            users = result.fetchall()
            
            # V2に変換して挿入
            for user in users:
                await v2_conn.execute("""
                    INSERT INTO users (id, username, email, password_hash, full_name, role, is_active, is_approved, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """, (
                    user.id,
                    user.username,
                    user.email,
                    user.password_hash,
                    user.full_name,
                    user.role,
                    user.is_active,
                    user.is_approved,
                    user.created_at
                ))

async def main():
    await migrate_users()
    await migrate_servers()
    await migrate_groups()
    await migrate_backups()
    print("移行が正常に完了しました！")

if __name__ == "__main__":
    asyncio.run(main())
```

## データベースセキュリティ

### 行レベルセキュリティ（RLS）
```sql
-- 機密テーブルでRLSを有効化
ALTER TABLE servers ENABLE ROW LEVEL SECURITY;
ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE backups ENABLE ROW LEVEL SECURITY;

-- ポリシーを作成
CREATE POLICY servers_owner_policy ON servers
    FOR ALL TO app_user
    USING (owner_id = current_setting('app.current_user_id')::UUID);

CREATE POLICY servers_admin_policy ON servers
    FOR ALL TO app_admin
    USING (true);

-- アプリケーションロールを作成
CREATE ROLE app_user;
CREATE ROLE app_admin;
CREATE ROLE app_operator;

-- 適切な権限を付与
GRANT SELECT, INSERT, UPDATE ON servers TO app_user;
GRANT ALL ON servers TO app_admin;
GRANT SELECT, UPDATE ON servers TO app_operator;
```

### 機密データ暗号化
```sql
-- 機密設定データを暗号化
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- サーバー設定を暗号化する関数
CREATE OR REPLACE FUNCTION encrypt_config(config_text TEXT, server_id UUID)
RETURNS TEXT AS $$
BEGIN
    RETURN pgp_sym_encrypt(config_text, server_id::TEXT);
END;
$$ LANGUAGE plpgsql;

-- サーバー設定を復号化する関数
CREATE OR REPLACE FUNCTION decrypt_config(encrypted_config TEXT, server_id UUID)
RETURNS TEXT AS $$
BEGIN
    RETURN pgp_sym_decrypt(encrypted_config, server_id::TEXT);
END;
$$ LANGUAGE plpgsql;
```

この包括的なデータベース設計は、適切な正規化、パフォーマンス最適化、セキュリティ対策、拡張性の考慮を備えたMinecraft Server Dashboard API V2の強固な基盤を提供します。