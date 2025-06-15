# Minecraft Server Dashboard API V2 - アーキテクチャ設計書

## 概要

この文書は、Minecraft Server Dashboard APIをゼロから再構築するための完全なアーキテクチャ設計を概説しています。現在のシステムで特定された複雑性の問題に対処しながら、6つの境界付きコンテキストを通じてコア機能を維持します。

## アーキテクチャの理念

### 中核原則
1. **ドメイン駆動設計（DDD）**：明確な境界を持つビジネスドメインを中心にコードを整理
2. **クリーンアーキテクチャ**：インフラストラクチャを外層とした依存関係の逆転
3. **CQRS + イベントソーシング**：イベント駆動アーキテクチャによる読み取り/書き込み操作の分離
4. **マイクロサービス対応**：分散アーキテクチャに拡張可能なモジュラー設計
5. **テスタビリティファースト**：依存性注入による容易なテスト設計
6. **フェイルファスト設計**：早期検証とエラー処理

### アーキテクチャパターン
- **ヘキサゴナルアーキテクチャ**：ビジネスロジックとインフラストラクチャの明確な分離
- **コマンドクエリ責任分離（CQRS）**：読み取りモデルと書き込みモデルの分離
- **イベント駆動アーキテクチャ**：ドメインイベントを通じたコンポーネントの疎結合
- **リポジトリパターン**：クリーンなインターフェースでデータアクセスを抽象化
- **ユニットオブワークパターン**：一貫したデータベーストランザクション管理

## ハイレベルアーキテクチャ

```
┌─────────────────────────────────────────────────────────────┐
│                    プレゼンテーション層                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   REST API  │  │  WebSocket  │  │  GraphQL    │        │
│  │  (FastAPI)  │  │   ゲートウェイ│  │  (オプション) │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                   アプリケーション層                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │  コマンド    │  │    クエリ     │  │   イベント   │        │
│  │  ハンドラー  │  │   ハンドラー  │  │  ハンドラー  │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    ドメイン層                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   ドメイン   │  │   ドメイン   │  │   ドメイン   │        │
│  │  サービス    │  │   イベント   │  │   モデル     │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                インフラストラクチャ層                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │ リポジトリ   │  │  外部API     │  │ バックグラウンド│        │
│  │ (データベース)│  │              │  │   タスク      │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

## 技術スタック V2

### コアフレームワーク
- **Python 3.12+**：パフォーマンス改善のための最新安定版
- **FastAPI 0.115+**：非同期パフォーマンスと自動OpenAPIのためFastAPIを継続使用
- **Pydantic V2**：強化されたバリデーションとシリアライゼーション
- **SQLAlchemy 2.0**：改善されたクエリパターンを持つモダンな非同期ORM
- **Alembic**：データベースマイグレーション管理

### データベース＆ストレージ
- **PostgreSQL 15+**：ACID準拠とJSONサポートのためのプライマリデータベース
- **Redis 7+**：セッションストレージ、キャッシング、リアルタイム機能のためのpub/sub
- **MinIO/S3**：バックアップと大容量ファイルのためのオブジェクトストレージ
- **ClickHouse**：メトリクスと監査ログのためのオプション時系列データベース

### メッセージキュー＆バックグラウンド処理
- **RQ (Redis Queue)**：Redisを使用したバックグラウンドジョブ処理
- **APScheduler**：スケジュールタスク管理
- **Celery**：複雑な分散タスクのためのオプションアップグレードパス

### リアルタイム＆通信
- **FastAPI WebSockets**：リアルタイム通信
- **Server-Sent Events (SSE)**：シンプルなクライアント向けのWebSocketsの代替
- **Redis Pub/Sub**：サービス間通信

### 開発＆デプロイメント
- **UV**：高速なPythonパッケージマネージャーとプロジェクト管理
- **Ruff**：超高速リンティングとフォーマッティング
- **Pytest**：包括的なテストフレームワーク
- **Docker**：開発とデプロイメントのためのコンテナ化
- **Traefik**：APIゲートウェイとロードバランサー

### 監視＆可観測性
- **Structlog**：構造化ログ
- **Prometheus**：メトリクス収集
- **Grafana**：可視化とダッシュボード
- **Sentry**：エラートラッキングとパフォーマンス監視

## ドメイン駆動設計構造

### 境界付きコンテキスト

#### 1. ユーザー管理コンテキスト
```
users/
├── domain/
│   ├── entities/
│   │   ├── user.py
│   │   └── user_session.py
│   ├── value_objects/
│   │   ├── user_id.py
│   │   ├── email.py
│   │   └── password.py
│   ├── repositories/
│   │   └── user_repository.py
│   ├── events/
│   │   ├── user_registered.py
│   │   └── user_approved.py
│   └── services/
│       └── user_service.py
├── application/
│   ├── commands/
│   │   ├── register_user.py
│   │   └── approve_user.py
│   ├── queries/
│   │   └── get_user_profile.py
│   └── handlers/
│       ├── command_handlers.py
│       └── query_handlers.py
├── infrastructure/
│   ├── repositories/
│   │   └── sql_user_repository.py
│   └── adapters/
│       └── auth_adapter.py
└── api/
    └── user_router.py
```

#### 2. サーバー管理コンテキスト
```
servers/
├── domain/
│   ├── entities/
│   │   ├── minecraft_server.py
│   │   └── server_configuration.py
│   ├── value_objects/
│   │   ├── server_id.py
│   │   ├── port.py
│   │   └── java_version.py
│   ├── repositories/
│   │   └── server_repository.py
│   ├── events/
│   │   ├── server_created.py
│   │   └── server_started.py
│   └── services/
│       ├── server_lifecycle_service.py
│       └── process_manager_service.py
├── application/
│   ├── commands/
│   │   ├── create_server.py
│   │   └── start_server.py
│   ├── queries/
│   │   └── get_server_status.py
│   └── handlers/
├── infrastructure/
│   ├── repositories/
│   ├── adapters/
│   │   ├── minecraft_process_adapter.py
│   │   └── file_system_adapter.py
│   └── external/
│       └── minecraft_api_client.py
└── api/
    └── server_router.py
```

#### 3. グループ管理コンテキスト
```
groups/
├── domain/
│   ├── entities/
│   │   ├── player_group.py
│   │   └── player.py
│   ├── value_objects/
│   │   ├── group_id.py
│   │   ├── minecraft_uuid.py
│   │   └── username.py
│   ├── repositories/
│   │   └── group_repository.py
│   ├── events/
│   │   ├── player_added.py
│   │   └── group_attached.py
│   └── services/
│       └── group_management_service.py
├── application/
├── infrastructure/
└── api/
```

#### 4. バックアップ管理コンテキスト
```
backups/
├── domain/
│   ├── entities/
│   │   ├── backup.py
│   │   └── backup_schedule.py
│   ├── value_objects/
│   │   ├── backup_id.py
│   │   └── cron_expression.py
│   ├── repositories/
│   │   └── backup_repository.py
│   ├── events/
│   │   ├── backup_created.py
│   │   └── backup_scheduled.py
│   └── services/
│       ├── backup_service.py
│       └── schedule_service.py
├── application/
├── infrastructure/
│   └── adapters/
│       └── storage_adapter.py
└── api/
```

#### 5. ファイル管理コンテキスト
```
files/
├── domain/
│   ├── entities/
│   │   ├── server_file.py
│   │   └── file_history.py
│   ├── value_objects/
│   │   ├── file_path.py
│   │   └── file_content.py
│   ├── repositories/
│   │   └── file_repository.py
│   ├── events/
│   │   └── file_modified.py
│   └── services/
│       └── file_management_service.py
├── application/
├── infrastructure/
│   └── adapters/
│       └── file_system_adapter.py
└── api/
```

#### 6. 監視コンテキスト
```
monitoring/
├── domain/
│   ├── entities/
│   │   ├── server_metrics.py
│   │   └── audit_log.py
│   ├── value_objects/
│   │   └── metric_value.py
│   ├── repositories/
│   │   └── metrics_repository.py
│   ├── events/
│   │   └── metric_recorded.py
│   └── services/
│       └── monitoring_service.py
├── application/
├── infrastructure/
│   └── adapters/
│       └── metrics_collector.py
└── api/
```

### 共有カーネル
```
shared/
├── domain/
│   ├── value_objects/
│   │   ├── entity_id.py
│   │   └── created_at.py
│   ├── events/
│   │   └── domain_event.py
│   └── exceptions/
│       └── domain_exception.py
├── application/
│   ├── commands/
│   │   └── command.py
│   ├── queries/
│   │   └── query.py
│   └── handlers/
│       └── handler.py
└── infrastructure/
    ├── database/
    │   ├── base_repository.py
    │   └── unit_of_work.py
    ├── events/
    │   └── event_publisher.py
    └── cache/
        └── cache_service.py
```

## イベント駆動アーキテクチャ

### ドメインイベント

#### ユーザーイベント
- `UserRegistered`（ユーザー登録）
- `UserApproved`（ユーザー承認）
- `UserRoleChanged`（ユーザーロール変更）
- `UserLoggedIn`（ユーザーログイン）
- `UserLoggedOut`（ユーザーログアウト）

#### サーバーイベント
- `ServerCreated`（サーバー作成）
- `ServerStarted`（サーバー開始）
- `ServerStopped`（サーバー停止）
- `ServerConfigurationUpdated`（サーバー設定更新）
- `ServerDeleted`（サーバー削除）
- `ConsoleCommandExecuted`（コンソールコマンド実行）

#### グループイベント
- `GroupCreated`（グループ作成）
- `PlayerAddedToGroup`（プレイヤーをグループに追加）
- `PlayerRemovedFromGroup`（プレイヤーをグループから削除）
- `GroupAttachedToServer`（グループをサーバーに接続）
- `GroupDetachedFromServer`（グループをサーバーから切断）

#### バックアップイベント
- `BackupCreated`（バックアップ作成）
- `BackupScheduled`（バックアップスケジュール設定）
- `BackupCompleted`（バックアップ完了）
- `BackupFailed`（バックアップ失敗）
- `BackupRestored`（バックアップ復元）

### イベントハンドラー

イベントは以下によって処理されます：
1. **即時ハンドラー**：読み取りモデルの更新、通知の送信
2. **バックグラウンドハンドラー**：長時間実行される操作（バックアップ作成、ファイル処理）
3. **統合ハンドラー**：外部システムの更新、Webhookのトリガー

### イベントストア

JSONBを使用したPostgreSQLでのイベントストレージ：
```sql
CREATE TABLE domain_events (
    id UUID PRIMARY KEY,
    aggregate_type VARCHAR(50) NOT NULL,
    aggregate_id UUID NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    event_data JSONB NOT NULL,
    event_version INTEGER NOT NULL,
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE
);
```

## CQRS実装

### コマンド側
- **コマンド**：バリデーション付きの書き込み操作を表現
- **コマンドハンドラー**：ビジネスロジックを実行しイベントを発行
- **アグリゲート**：境界付きコンテキスト内の一貫性を確保
- **リポジトリ**：アグリゲート状態を永続化

### クエリ側
- **クエリ**：特定のデータニーズを持つ読み取り操作を表現
- **クエリハンドラー**：最適化された読み取りモデルを返す
- **読み取りモデル**：特定のクエリ用に最適化された非正規化ビュー
- **プロジェクション**：ドメインイベントから読み取りモデルを更新

### 読み取りモデルの例

#### サーバーリスト読み取りモデル
```python
@dataclass
class ServerListItem:
    id: UUID
    name: str
    status: ServerStatus
    player_count: int
    version: str
    created_at: datetime
    owner_username: str
```

#### バックアップサマリー読み取りモデル
```python
@dataclass
class BackupSummary:
    server_id: UUID
    server_name: str
    backup_count: int
    latest_backup: datetime
    total_size: int
    success_rate: float
```

## データベース設計 V2

### 書き込みモデル（正規化）
```sql
-- ユーザーテーブル
CREATE TABLE users (
    id UUID PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    is_active BOOLEAN DEFAULT true,
    is_approved BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    version INTEGER DEFAULT 1
);

-- サーバーテーブル
CREATE TABLE servers (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    owner_id UUID REFERENCES users(id),
    port INTEGER UNIQUE NOT NULL,
    status VARCHAR(20) DEFAULT 'stopped',
    configuration JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    version INTEGER DEFAULT 1
);

-- グループテーブル
CREATE TABLE groups (
    id UUID PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    group_type VARCHAR(20) NOT NULL, -- 'op' または 'whitelist'
    owner_id UUID REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    version INTEGER DEFAULT 1
);

-- プレイヤーテーブル
CREATE TABLE players (
    id UUID PRIMARY KEY,
    minecraft_uuid UUID UNIQUE NOT NULL,
    username VARCHAR(16) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- グループプレイヤー結合テーブル
CREATE TABLE group_players (
    group_id UUID REFERENCES groups(id) ON DELETE CASCADE,
    player_id UUID REFERENCES players(id) ON DELETE CASCADE,
    added_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (group_id, player_id)
);

-- サーバーグループ結合テーブル
CREATE TABLE server_groups (
    server_id UUID REFERENCES servers(id) ON DELETE CASCADE,
    group_id UUID REFERENCES groups(id) ON DELETE CASCADE,
    priority INTEGER DEFAULT 0,
    attached_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (server_id, group_id)
);

-- バックアップテーブル
CREATE TABLE backups (
    id UUID PRIMARY KEY,
    server_id UUID REFERENCES servers(id),
    name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    size_bytes BIGINT,
    backup_type VARCHAR(20) DEFAULT 'manual', -- 'manual' または 'scheduled'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- バックアップスケジュールテーブル
CREATE TABLE backup_schedules (
    id UUID PRIMARY KEY,
    server_id UUID REFERENCES servers(id),
    cron_expression VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    last_run TIMESTAMP WITH TIME ZONE,
    next_run TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

```

### 読み取りモデル（非正規化）
```sql
-- サーバーリストビュー
CREATE MATERIALIZED VIEW server_list_view AS
SELECT 
    s.id,
    s.name,
    s.status,
    s.port,
    s.configuration->>'version' as version,
    s.created_at,
    u.username as owner_username,
    COUNT(b.id) as backup_count,
    MAX(b.created_at) as latest_backup
FROM servers s
LEFT JOIN users u ON s.owner_id = u.id
LEFT JOIN backups b ON s.id = b.server_id
GROUP BY s.id, s.name, s.status, s.port, s.configuration, s.created_at, u.username;

-- グループサマリービュー
CREATE MATERIALIZED VIEW group_summary_view AS
SELECT 
    g.id,
    g.name,
    g.group_type,
    g.created_at,
    u.username as owner_username,
    COUNT(DISTINCT gp.player_id) as player_count,
    COUNT(DISTINCT sg.server_id) as server_count
FROM groups g
LEFT JOIN users u ON g.owner_id = u.id
LEFT JOIN group_players gp ON g.id = gp.group_id
LEFT JOIN server_groups sg ON g.id = sg.group_id
GROUP BY g.id, g.name, g.group_type, g.created_at, u.username;
```

## API設計 V2

### RESTful API構造
```
/api/v2/
├── auth/
│   ├── POST /register
│   ├── POST /login
│   ├── POST /refresh
│   └── POST /logout
├── users/
│   ├── GET /me
│   ├── PUT /me
│   ├── GET /
│   └── PATCH /{user_id}/approve
├── servers/
│   ├── GET /
│   ├── POST /
│   ├── GET /{server_id}
│   ├── PUT /{server_id}
│   ├── DELETE /{server_id}
│   ├── POST /{server_id}/start
│   ├── POST /{server_id}/stop
│   ├── POST /{server_id}/restart
│   ├── GET /{server_id}/status
│   ├── POST /{server_id}/console
│   └── GET /{server_id}/logs
├── groups/
│   ├── GET /
│   ├── POST /
│   ├── GET /{group_id}
│   ├── PUT /{group_id}
│   ├── DELETE /{group_id}
│   ├── POST /{group_id}/players
│   ├── DELETE /{group_id}/players/{player_id}
│   ├── POST /{group_id}/servers/{server_id}
│   └── DELETE /{group_id}/servers/{server_id}
├── backups/
│   ├── GET /servers/{server_id}/backups
│   ├── POST /servers/{server_id}/backups
│   ├── GET /backups/{backup_id}
│   ├── DELETE /backups/{backup_id}
│   ├── POST /backups/{backup_id}/restore
│   ├── GET /servers/{server_id}/schedules
│   ├── POST /servers/{server_id}/schedules
│   └── DELETE /schedules/{schedule_id}
├── files/
│   ├── GET /servers/{server_id}/files
│   ├── GET /servers/{server_id}/files/{file_path}
│   ├── PUT /servers/{server_id}/files/{file_path}
│   ├── DELETE /servers/{server_id}/files/{file_path}
│   └── GET /servers/{server_id}/files/{file_path}/history
└── admin/
    ├── GET /users
    ├── GET /system/sync
    ├── GET /cache/stats
    └── GET /audit
```

### WebSocket API
```
/ws/
├── servers/{server_id}/
│   ├── status    # サーバーステータス更新
│   ├── logs      # リアルタイムログストリーミング
│   └── console   # インタラクティブコンソール
├── notifications # グローバルユーザー通知
└── metrics       # システムメトリクス（管理者用）
```

### コマンド/クエリ分離
```python
# コマンド（書き込み操作）
class CreateServerCommand:
    name: str
    description: str
    version: str
    memory_mb: int
    owner_id: UUID

class StartServerCommand:
    server_id: UUID
    
# クエリ（読み取り操作）
class GetServerListQuery:
    owner_id: Optional[UUID] = None
    status: Optional[ServerStatus] = None
    page: int = 1
    limit: int = 20

class GetServerDetailsQuery:
    server_id: UUID
    include_metrics: bool = False
```

## セキュリティアーキテクチャ

### 認証＆認可
```python
# JWT Claims構造
{
    "sub": "user_id",
    "username": "john_doe",
    "role": "operator",
    "permissions": ["server:read", "server:write", "group:read"],
    "exp": 1234567890,
    "iat": 1234567890
}

# パーミッションシステム
class Permission:
    ADMIN_ALL = "admin:*"
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    SERVER_READ = "server:read"
    SERVER_WRITE = "server:write"
    SERVER_CONSOLE = "server:console"
    GROUP_READ = "group:read"
    GROUP_WRITE = "group:write"
    BACKUP_READ = "backup:read"
    BACKUP_WRITE = "backup:write"
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
```

### 入力検証
```python
from pydantic import BaseModel, validator, Field
from typing import Optional
import re

class CreateServerRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    version: str = Field(..., regex=r'^\d+\.\d+(\.\d+)?$')
    memory_mb: int = Field(..., ge=512, le=32768)
    
    @validator('name')
    def validate_server_name(cls, v):
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('サーバー名は英数字、アンダースコア、ハイフンのみ使用可能です')
        return v

class ConsoleCommandRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=200)
    
    @validator('command')
    def validate_command(cls, v):
        dangerous_commands = ['rm', 'del', 'format', 'shutdown', 'restart']
        if any(cmd in v.lower() for cmd in dangerous_commands):
            raise ValueError('危険なコマンドは許可されていません')
        return v
```

### レート制限
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# レート制限設定
RATE_LIMITS = {
    "auth": "5/minute",
    "console": "30/minute", 
    "api_general": "100/minute",
    "websocket": "1000/minute"
}
```

## パフォーマンス最適化

### データベース最適化
```sql
-- 一般的なクエリ用のインデックス
CREATE INDEX idx_servers_owner_status ON servers(owner_id, status);
CREATE INDEX idx_backups_server_created ON backups(server_id, created_at DESC);
CREATE INDEX idx_groups_owner_type ON groups(owner_id, group_type);
CREATE INDEX idx_domain_events_aggregate ON domain_events(aggregate_type, aggregate_id);

-- アクティブレコード用の部分インデックス
CREATE INDEX idx_users_active ON users(id) WHERE is_active = true AND is_approved = true;
CREATE INDEX idx_schedules_active ON backup_schedules(server_id, next_run) WHERE is_active = true;
```

### キャッシング戦略
```python
# Redisキャッシングレイヤー
CACHE_KEYS = {
    "server_status": "server:{server_id}:status",  # TTL: 30秒
    "user_permissions": "user:{user_id}:perms",    # TTL: 15分
    "server_list": "servers:list:{owner_id}",      # TTL: 5分
    "backup_summary": "backup:summary:{server_id}" # TTL: 1時間
}

# キャッシュ無効化パターン
CACHE_INVALIDATION = {
    "ServerStarted": ["server:{server_id}:status", "servers:list:*"],
    "BackupCreated": ["backup:summary:{server_id}"],
    "UserRoleChanged": ["user:{user_id}:perms"]
}
```

### 非同期操作
```python
# バックグラウンドジョブキュー
JOB_QUEUES = {
    "high_priority": ["server_start", "server_stop"],
    "normal_priority": ["backup_create", "file_upload"],
    "low_priority": ["metrics_collection", "cleanup_tasks"]
}

# 非同期サービス実装
class AsyncServerService:
    async def start_server(self, server_id: UUID) -> None:
        # 進行状況追跡付きの非ブロッキングサーバー起動
        job = await self.job_queue.enqueue(
            "start_server_job", 
            server_id, 
            queue="high_priority"
        )
        await self.event_publisher.publish(
            ServerStartRequested(server_id=server_id, job_id=job.id)
        )
```

## テスト戦略

### テストアーキテクチャ
```
tests/
├── unit/
│   ├── domain/
│   │   ├── test_entities.py
│   │   ├── test_value_objects.py
│   │   └── test_services.py
│   ├── application/
│   │   ├── test_command_handlers.py
│   │   └── test_query_handlers.py
│   └── infrastructure/
│       ├── test_repositories.py
│       └── test_adapters.py
├── integration/
│   ├── test_api_endpoints.py
│   ├── test_database_operations.py
│   └── test_event_handling.py
├── e2e/
│   ├── test_user_workflows.py
│   ├── test_server_lifecycle.py
│   └── test_backup_workflows.py
└── performance/
    ├── test_load_scenarios.py
    └── test_concurrent_users.py
```

### テストカバレッジ目標
- ユニットテスト：>90%のカバレッジ
- 統合テスト：すべてのAPIエンドポイント
- E2Eテスト：重要なユーザージャーニー
- パフォーマンステスト：同時実行操作のロードテスト

## デプロイメントアーキテクチャ

### コンテナ戦略
```dockerfile
# 本番用マルチステージビルド
FROM python:3.12-slim as builder
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim as runtime
COPY --from=builder /app/.venv /app/.venv
COPY ./app /app/app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Docker Composeセットアップ
```yaml
version: '3.8'
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/mcapi
      - REDIS_URL=redis://redis:6379
    depends_on:
      - postgres
      - redis
      
  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=mcapi
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data
      
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
      
  worker:
    build: .
    command: rq worker --url redis://redis:6379
    depends_on:
      - redis
      - postgres
      
volumes:
  postgres_data:
  redis_data:
```

### 本番デプロイメント
```yaml
# Kubernetesデプロイメントの例
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcapi-deployment
spec:
  replicas: 3
  selector:
    matchLabels:
      app: mcapi
  template:
    metadata:
      labels:
        app: mcapi
    spec:
      containers:
      - name: mcapi
        image: mcapi:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: mcapi-secrets
              key: database-url
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
```

## 移行戦略

### フェーズ 1: 基盤（第1-2週）
1. 新しいプロジェクト構造の設定
2. 共有カーネルとコアドメインモデルの実装
3. データベースと基本的なCRUD操作の設定
4. 認証と認可の実装

### フェーズ 2: コアドメイン（第3-6週）
1. ユーザー管理ドメイン
2. サーバー管理ドメイン（基本操作）
3. グループ管理ドメイン
4. 基本的なAPIエンドポイントとバリデーション

### フェーズ 3: 高度な機能（第7-10週）
1. バックアップ管理ドメイン
2. ファイル管理ドメイン
3. バックグラウンドジョブ処理

### フェーズ 4: リアルタイム＆監視（第11-12週）
1. WebSocket実装
2. 監視とメトリクス
3. イベント駆動アーキテクチャの完成
4. パフォーマンス最適化

### フェーズ 5: 移行＆デプロイメント（第13-14週）
1. V1からのデータ移行
2. 本番デプロイメント
3. ロードテストと最適化
4. ドキュメントとトレーニング

## 成功指標

### 技術的指標
- コードカバレッジ：>90%
- API応答時間：<200ms（95パーセンタイル）
- データベースクエリ時間：<50ms（平均）
- メモリ使用量：インスタンスあたり<512MB
- CPU使用率：通常負荷で<50%

### ビジネス指標
- 500以上の同時サーバーをサポート
- 99.9%のアップタイム
- ゼロデータロス
- <1秒のリアルタイムイベント伝播
- 1000以上の同時WebSocket接続をサポート

## 結論

このアーキテクチャ設計は、保守性、拡張性、テスト可能性を向上させたMinecraft Server Dashboard APIを再構築するための強固な基盤を提供します。ドメイン駆動設計アプローチにより懸念事項の明確な分離が保証され、イベント駆動アーキテクチャにより疎結合とより良い拡張性が実現されます。

V1からV2への移行は、改善されたコード組織と技術的負債の削減を通じて即座の価値を提供しながら、中断を最小限に抑えるために段階的に実行されます。