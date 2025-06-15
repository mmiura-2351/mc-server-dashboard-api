# API設計 - Minecraft Server Dashboard API V2

## 概要

この文書は、Minecraft Server Dashboard API V2の包括的なAPI設計を提供します。RESTfulエンドポイント、WebSocket接続、認証メカニズム、リクエスト/レスポンススキーマ、エラーハンドリング、OpenAPI仕様が含まれています。

## APIアーキテクチャ

### 設計原則
1. **RESTful設計**: 適切なHTTPメソッドを使用したリソース指向URL
2. **一貫した命名**: JSONフィールドはsnake_case、URLはkebab-case
3. **バージョニング**: URLベースのバージョニング（`/api/v2/`）
4. **ステートレス**: RESTエンドポイントではサーバーサイドセッション状態なし
5. **HATEOAS**: レスポンスに関連リンクを含める
6. **コンテンツネゴシエーション**: JSON（プライマリ）とオプション形式をサポート

### 技術スタック
- **フレームワーク**: 自動OpenAPI生成付きFastAPI
- **認証**: JWTベアラートークン
- **バリデーション**: 包括的なバリデーション付きPydanticモデル
- **ドキュメント**: 自動生成OpenAPI/Swagger文書
- **レート制限**: Redisベースレート制限
- **リアルタイム**: ライブ更新用WebSocket接続

## 認証と認可

### JWTトークン構造
```json
{
  "sub": "user_id",
  "username": "john_doe",
  "email": "john@example.com",
  "role": "operator",
  "permissions": [
    "server:read",
    "server:write",
    "group:read",
    "backup:read"
  ],
  "iat": 1640995200,
  "exp": 1641081600,
  "jti": "token_id"
}
```

### 権限システム
```python
class Permissions:
    # 管理者権限
    ADMIN_ALL = "admin:*"
    USER_MANAGE = "user:manage"
    
    # ユーザー権限
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    
    # サーバー権限
    SERVER_READ = "server:read"
    SERVER_WRITE = "server:write"
    SERVER_CONTROL = "server:control"
    SERVER_CONSOLE = "server:console"
    SERVER_DELETE = "server:delete"
    
    # グループ権限
    GROUP_READ = "group:read"
    GROUP_WRITE = "group:write"
    GROUP_DELETE = "group:delete"
    
    # バックアップ権限
    BACKUP_READ = "backup:read"
    BACKUP_WRITE = "backup:write"
    BACKUP_DELETE = "backup:delete"
    
    
    # ファイル権限
    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    FILE_DELETE = "file:delete"
    
    # 監視権限
    METRICS_READ = "metrics:read"
    AUDIT_READ = "audit:read"
```

## APIエンドポイント

### ベースURL
- **本番環境**: `https://api.mcserver.example.com/api/v2`
- **開発環境**: `http://localhost:8000/api/v2`

### 1. 認証エンドポイント

#### POST /auth/register
新しいユーザーアカウントを登録する。

**リクエストボディ:**
```json
{
  "username": "john_doe",
  "email": "john@example.com",
  "password": "SecurePassword123!",
  "full_name": "田中太郎"
}
```

**レスポンス (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "john_doe",
  "email": "john@example.com",
  "full_name": "田中太郎",
  "role": "user",
  "is_active": true,
  "is_approved": false,
  "created_at": "2024-01-15T10:30:00Z",
  "message": "登録が成功しました。アカウントには管理者の承認が必要です。"
}
```

#### POST /auth/login
ユーザーを認証してアクセストークンを受け取る。

**リクエストボディ:**
```json
{
  "username": "john_doe",
  "password": "SecurePassword123!"
}
```

**レスポンス (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "john_doe",
    "email": "john@example.com",
    "role": "operator",
    "permissions": ["server:read", "server:write"]
  }
}
```

#### POST /auth/refresh
リフレッシュトークンを使用してアクセストークンを更新する。

**リクエストボディ:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

#### POST /auth/logout
ログアウトしてトークンを無効化する。

**ヘッダー:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### 2. ユーザー管理エンドポイント

#### GET /users/me
現在のユーザープロフィールを取得する。

**レスポンス (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "username": "john_doe",
  "email": "john@example.com",
  "full_name": "田中太郎",
  "role": "operator",
  "is_active": true,
  "is_approved": true,
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-16T08:15:00Z",
  "last_login": "2024-01-16T09:00:00Z",
  "permissions": ["server:read", "server:write", "group:read"],
  "statistics": {
    "servers_count": 5,
    "groups_count": 3,
    "backups_count": 15
  },
  "_links": {
    "self": "/api/v2/users/me",
    "servers": "/api/v2/servers?owner_id=550e8400-e29b-41d4-a716-446655440000"
  }
}
```

#### PUT /users/me
現在のユーザープロフィールを更新する。

**リクエストボディ:**
```json
{
  "email": "newemail@example.com",
  "full_name": "田中次郎",
  "password": "NewSecurePassword123!"
}
```

#### GET /users
すべてのユーザーをリストする（管理者のみ）。

**クエリパラメータ:**
- `page` (integer, default: 1): ページ番号
- `limit` (integer, default: 20, max: 100): ページあたりのアイテム数
- `role` (string): ロールでフィルタ
- `is_approved` (boolean): 承認状況でフィルタ
- `search` (string): ユーザー名またはメールで検索

**レスポンス (200 OK):**
```json
{
  "users": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "username": "john_doe",
      "email": "john@example.com",
      "full_name": "田中太郎",
      "role": "operator",
      "is_active": true,
      "is_approved": true,
      "created_at": "2024-01-15T10:30:00Z",
      "last_login": "2024-01-16T09:00:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 1,
    "pages": 1
  },
  "_links": {
    "self": "/api/v2/users?page=1&limit=20",
    "next": null,
    "prev": null
  }
}
```

#### PATCH /users/{user_id}/approve
ユーザー登録を承認する（管理者のみ）。

**リクエストボディ:**
```json
{
  "is_approved": true,
  "role": "operator"
}
```

### 3. サーバー管理エンドポイント

#### GET /servers
ユーザーのサーバーをリストする。

**クエリパラメータ:**
- `page` (integer): ページ番号
- `limit` (integer): ページあたりのアイテム数
- `status` (string): ステータスでフィルタ
- `server_type` (string): サーバータイプでフィルタ
- `search` (string): 名前または説明で検索
- `sort` (string): ソートフィールド (created_at, name, status)
- `order` (string): ソート順 (asc, desc)

**レスポンス (200 OK):**
```json
{
  "servers": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "survival-world",
      "description": "メインサバイバルサーバー",
      "status": "running",
      "port": 25565,
      "minecraft_version": "1.21.5",
      "server_type": "paper",
      "memory_mb": 4096,
      "player_count": 5,
      "max_players": 20,
      "created_at": "2024-01-15T10:30:00Z",
      "last_started_at": "2024-01-16T08:00:00Z",
      "owner": {
        "id": "440e8400-e29b-41d4-a716-446655440000",
        "username": "john_doe"
      },
      "statistics": {
        "uptime_hours": 168,
        "total_playtime_hours": 2340,
        "backup_count": 8,
        "attached_groups": 2
      },
      "_links": {
        "self": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000",
        "start": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/start",
        "stop": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/stop",
        "console": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/console",
        "logs": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/logs",
        "backups": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/backups"
      }
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 1,
    "pages": 1
  },
  "summary": {
    "total_servers": 1,
    "running_servers": 1,
    "stopped_servers": 0,
    "total_memory_mb": 4096
  }
}
```

#### POST /servers
新しいサーバーを作成する。

**リクエストボディ:**
```json
{
  "name": "creative-build",
  "description": "クリエイティブ建築サーバー",
  "minecraft_version": "1.21.5",
  "server_type": "paper",
  "memory_mb": 2048,
  "port": 25566,
  "auto_start": false,
  "auto_restart": true,
  "java_args": "-XX:+UseG1GC -XX:MaxGCPauseMillis=50",
  "configuration": {
    "gamemode": "creative",
    "difficulty": "peaceful",
    "max_players": 10,
    "view_distance": 8,
    "spawn_protection": 0
  }
}
```

**レスポンス (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "creative-build",
  "description": "クリエイティブ建築サーバー",
  "status": "stopped",
  "port": 25566,
  "minecraft_version": "1.21.5",
  "server_type": "paper",
  "memory_mb": 2048,
  "owner_id": "440e8400-e29b-41d4-a716-446655440000",
  "created_at": "2024-01-16T10:30:00Z",
  "configuration": {
    "gamemode": "creative",
    "difficulty": "peaceful",
    "max_players": 10,
    "view_distance": 8,
    "spawn_protection": 0
  },
  "_links": {
    "self": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000",
    "start": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/start"
  }
}
```

#### GET /servers/{server_id}
サーバーの詳細を取得する。

**レスポンス (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "survival-world",
  "description": "メインサバイバルサーバー",
  "status": "running",
  "port": 25565,
  "minecraft_version": "1.21.5",
  "server_type": "paper",
  "memory_mb": 4096,
  "java_args": "-XX:+UseG1GC -XX:MaxGCPauseMillis=50",
  "auto_start": false,
  "auto_restart": true,
  "process_id": 12345,
  "created_at": "2024-01-15T10:30:00Z",
  "last_started_at": "2024-01-16T08:00:00Z",
  "owner": {
    "id": "440e8400-e29b-41d4-a716-446655440000",
    "username": "john_doe",
    "full_name": "田中太郎"
  },
  "configuration": {
    "gamemode": "survival",
    "difficulty": "normal",
    "max_players": 20,
    "view_distance": 10,
    "spawn_protection": 16,
    "enable_whitelist": true
  },
  "runtime_info": {
    "uptime_seconds": 28800,
    "cpu_usage_percent": 15.5,
    "memory_usage_mb": 3072,
    "disk_usage_mb": 2048,
    "tps": 19.8,
    "player_count": 5,
    "players_online": [
      {
        "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
        "username": "player1",
        "display_name": "プレイヤー1"
      }
    ]
  },
  "file_structure": {
    "world_size_mb": 150,
    "plugin_count": 8,
    "mod_count": 0
  },
  "_links": {
    "self": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000",
    "start": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/start",
    "stop": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/stop",
    "restart": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/restart",
    "console": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/console",
    "logs": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/logs",
    "files": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files",
    "backups": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/backups",
    "groups": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/groups"
  }
}
```

#### PUT /servers/{server_id}
サーバー設定を更新する。

**リクエストボディ:**
```json
{
  "name": "updated-survival-world",
  "description": "更新された説明",
  "memory_mb": 6144,
  "auto_restart": false,
  "configuration": {
    "max_players": 25,
    "view_distance": 12
  }
}
```

#### DELETE /servers/{server_id}
サーバーを削除する（ソフト削除）。

**レスポンス (204 No Content)**

#### POST /servers/{server_id}/start
サーバーを起動する。

**リクエストボディ (オプション):**
```json
{
  "force": false,
  "wait_for_startup": true
}
```

**レスポンス (202 Accepted):**
```json
{
  "message": "サーバー起動を開始しました",
  "job_id": "660e8400-e29b-41d4-a716-446655440000",
  "estimated_startup_time": 30,
  "_links": {
    "status": "/api/v2/jobs/660e8400-e29b-41d4-a716-446655440000",
    "server": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000"
  }
}
```

#### POST /servers/{server_id}/stop
サーバーを停止する。

**リクエストボディ (オプション):**
```json
{
  "force": false,
  "save_world": true,
  "timeout_seconds": 30
}
```

#### POST /servers/{server_id}/restart
サーバーを再起動する。

#### GET /servers/{server_id}/status
リアルタイムサーバーステータスを取得する。

**レスポンス (200 OK):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "process_id": 12345,
  "uptime_seconds": 28800,
  "last_updated": "2024-01-16T14:30:00Z",
  "metrics": {
    "cpu_usage_percent": 15.5,
    "memory_usage_mb": 3072,
    "memory_max_mb": 4096,
    "disk_usage_mb": 2048,
    "network_in_kbps": 125,
    "network_out_kbps": 87,
    "tps": 19.8,
    "player_count": 5
  },
  "health": {
    "is_responding": true,
    "last_response_time_ms": 45,
    "error_count_last_hour": 0
  }
}
```

#### POST /servers/{server_id}/console
コンソールコマンドを送信する。

**リクエストボディ:**
```json
{
  "command": "say こんにちは、世界！",
  "wait_for_response": true,
  "timeout_seconds": 5
}
```

**レスポンス (200 OK):**
```json
{
  "command": "say こんにちは、世界！",
  "executed_at": "2024-01-16T14:30:00Z",
  "response": "[Server] こんにちは、世界！",
  "execution_time_ms": 15,
  "success": true
}
```

#### GET /servers/{server_id}/logs
サーバーログを取得する。

**クエリパラメータ:**
- `lines` (integer, default: 100): ログ行数
- `since` (ISO datetime): タイムスタンプ以降のログを取得
- `level` (string): ログレベルでフィルタ
- `search` (string): ログ内容で検索

**レスポンス (200 OK):**
```json
{
  "logs": [
    {
      "timestamp": "2024-01-16T14:30:00Z",
      "level": "INFO",
      "thread": "Server thread",
      "message": "[Server] こんにちは、世界！",
      "raw_line": "[14:30:00] [Server thread/INFO]: [Server] こんにちは、世界！"
    }
  ],
  "total_lines": 1,
  "has_more": false,
  "_links": {
    "websocket": "/ws/servers/550e8400-e29b-41d4-a716-446655440000/logs"
  }
}
```

### 4. グループ管理エンドポイント

#### GET /groups
ユーザーのグループをリストする。

**レスポンス (200 OK):**
```json
{
  "groups": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "admins",
      "description": "サーバー管理者",
      "group_type": "op",
      "is_public": false,
      "player_count": 3,
      "server_count": 2,
      "created_at": "2024-01-15T10:30:00Z",
      "players": [
        {
          "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
          "username": "player1",
          "display_name": "プレイヤー1",
          "added_at": "2024-01-15T11:00:00Z"
        }
      ],
      "_links": {
        "self": "/api/v2/groups/550e8400-e29b-41d4-a716-446655440000"
      }
    }
  ]
}
```

#### POST /groups
新しいグループを作成する。

**リクエストボディ:**
```json
{
  "name": "moderators",
  "description": "サーバーモデレーター",
  "group_type": "op",
  "is_public": false
}
```

#### GET /groups/{group_id}
グループの詳細を取得する。

#### PUT /groups/{group_id}
グループを更新する。

#### DELETE /groups/{group_id}
グループを削除する。

#### POST /groups/{group_id}/players
グループにプレイヤーを追加する。

**リクエストボディ:**
```json
{
  "username": "new_player"
}
```

**レスポンス (201 Created):**
```json
{
  "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
  "username": "new_player",
  "display_name": "新プレイヤー",
  "added_at": "2024-01-16T14:30:00Z",
  "skin_url": "https://textures.minecraft.net/texture/...",
  "profile": {
    "first_seen": "2024-01-10T12:00:00Z",
    "last_seen": "2024-01-16T13:45:00Z",
    "is_online": false
  }
}
```

#### DELETE /groups/{group_id}/players/{player_uuid}
グループからプレイヤーを削除する。

#### POST /groups/{group_id}/servers/{server_id}
グループをサーバーに接続する。

**リクエストボディ:**
```json
{
  "priority": 10
}
```

#### DELETE /groups/{group_id}/servers/{server_id}
グループをサーバーから切断する。

### 5. バックアップ管理エンドポイント

#### GET /servers/{server_id}/backups
サーバーバックアップをリストする。

**レスポンス (200 OK):**
```json
{
  "backups": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "daily-backup-2024-01-16",
      "description": "自動日次バックアップ",
      "file_path": "/backups/server_1_20240116_143000.tar.gz",
      "file_size_bytes": 157286400,
      "file_size_human": "150 MB",
      "compression_ratio": 0.65,
      "backup_type": "scheduled",
      "status": "completed",
      "world_name": "world",
      "minecraft_version": "1.21.5",
      "created_at": "2024-01-16T14:30:00Z",
      "completed_at": "2024-01-16T14:32:15Z",
      "duration_seconds": 135,
      "created_by": {
        "id": "440e8400-e29b-41d4-a716-446655440000",
        "username": "system"
      },
      "_links": {
        "self": "/api/v2/backups/550e8400-e29b-41d4-a716-446655440000",
        "download": "/api/v2/backups/550e8400-e29b-41d4-a716-446655440000/download",
        "restore": "/api/v2/backups/550e8400-e29b-41d4-a716-446655440000/restore"
      }
    }
  ],
  "pagination": {
    "page": 1,
    "limit": 20,
    "total": 1,
    "pages": 1
  },
  "summary": {
    "total_backups": 15,
    "total_size_bytes": 2361344000,
    "total_size_human": "2.2 GB",
    "success_rate": 98.5,
    "latest_backup": "2024-01-16T14:30:00Z"
  }
}
```

#### POST /servers/{server_id}/backups
手動バックアップを作成する。

**リクエストボディ:**
```json
{
  "name": "pre-update-backup",
  "description": "1.21.6への更新前バックアップ",
  "include_world": true,
  "include_plugins": true,
  "include_config": true,
  "compress": true
}
```

**レスポンス (202 Accepted):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "バックアップ作成を開始しました",
  "job_id": "660e8400-e29b-41d4-a716-446655440000",
  "estimated_duration_seconds": 120,
  "_links": {
    "status": "/api/v2/jobs/660e8400-e29b-41d4-a716-446655440000",
    "backup": "/api/v2/backups/550e8400-e29b-41d4-a716-446655440000"
  }
}
```

#### GET /backups/{backup_id}
バックアップの詳細を取得する。

#### DELETE /backups/{backup_id}
バックアップを削除する。

#### POST /backups/{backup_id}/restore
バックアップを新しいサーバーに復元する。

**リクエストボディ:**
```json
{
  "new_server_name": "restored-survival",
  "port": 25567,
  "memory_mb": 4096,
  "start_after_restore": false
}
```

#### GET /backups/{backup_id}/download
バックアップファイルをダウンロードする。

**レスポンス**: 適切なヘッダー付きバイナリファイルダウンロード。

#### GET /servers/{server_id}/backup-schedules
バックアップスケジュールをリストする。

#### POST /servers/{server_id}/backup-schedules
バックアップスケジュールを作成する。

**リクエストボディ:**
```json
{
  "name": "nightly-backup",
  "cron_expression": "0 2 * * *",
  "timezone": "UTC",
  "retention_count": 7,
  "retention_days": 30,
  "only_if_players_online": false,
  "compress_backup": true,
  "is_active": true
}
```

### 6. ファイル管理エンドポイント

#### GET /servers/{server_id}/files
サーバーファイルを参照する。

**クエリパラメータ:**
- `path` (string): 参照するディレクトリパス
- `file_type` (string): ファイルタイプでフィルタ
- `search` (string): ファイル名を検索

**レスポンス (200 OK):**
```json
{
  "current_path": "/plugins",
  "files": [
    {
      "name": "EssentialsX.jar",
      "path": "/plugins/EssentialsX.jar",
      "type": "file",
      "size_bytes": 1048576,
      "size_human": "1.0 MB",
      "mime_type": "application/java-archive",
      "is_editable": false,
      "modified_at": "2024-01-15T12:00:00Z",
      "permissions": "rw-r--r--",
      "_links": {
        "download": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/download?path=/plugins/EssentialsX.jar"
      }
    },
    {
      "name": "config.yml",
      "path": "/plugins/EssentialsX/config.yml",
      "type": "file",
      "size_bytes": 4096,
      "size_human": "4.0 KB",
      "mime_type": "text/yaml",
      "is_editable": true,
      "modified_at": "2024-01-16T10:30:00Z",
      "_links": {
        "view": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/view?path=/plugins/EssentialsX/config.yml",
        "edit": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/edit?path=/plugins/EssentialsX/config.yml",
        "history": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/history?path=/plugins/EssentialsX/config.yml"
      }
    }
  ],
  "breadcrumbs": [
    {
      "name": "root",
      "path": "/",
      "_links": {"browse": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files?path=/"}
    },
    {
      "name": "plugins",
      "path": "/plugins",
      "_links": {"browse": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files?path=/plugins"}
    }
  ]
}
```

#### GET /servers/{server_id}/files/view
ファイル内容を表示する。

**クエリパラメータ:**
- `path` (string, required): ファイルパス

**レスポンス (200 OK):**
```json
{
  "file_path": "/server.properties",
  "content": "# Minecraft server properties\nserver-port=25565\ngamemode=survival\n...",
  "content_type": "text/plain",
  "encoding": "utf-8",
  "size_bytes": 2048,
  "line_count": 45,
  "is_binary": false,
  "last_modified": "2024-01-16T10:30:00Z",
  "syntax_highlighting": "properties"
}
```

#### PUT /servers/{server_id}/files/edit
ファイル内容を編集する。

**クエリパラメータ:**
- `path` (string, required): ファイルパス

**リクエストボディ:**
```json
{
  "content": "# Updated Minecraft server properties\nserver-port=25565\ngamemode=creative\n...",
  "create_backup": true,
  "encoding": "utf-8"
}
```

#### POST /servers/{server_id}/files/upload
ファイルをアップロードする。

**リクエスト**: ファイル付きマルチパートフォームデータ

#### GET /servers/{server_id}/files/download
ファイルをダウンロードする。

**クエリパラメータ:**
- `path` (string, required): ファイルパス

#### DELETE /servers/{server_id}/files/delete
ファイルを削除する。

#### GET /servers/{server_id}/files/history
ファイル編集履歴を取得する。

**クエリパラメータ:**
- `path` (string, required): ファイルパス

**レスポンス (200 OK):**
```json
{
  "file_path": "/server.properties",
  "history": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "version": 3,
      "change_type": "modified",
      "size_bytes": 2048,
      "content_hash": "abc123...",
      "modified_at": "2024-01-16T10:30:00Z",
      "modified_by": {
        "id": "440e8400-e29b-41d4-a716-446655440000",
        "username": "john_doe"
      },
      "_links": {
        "view": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/history/550e8400-e29b-41d4-a716-446655440000",
        "restore": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000/files/restore/550e8400-e29b-41d4-a716-446655440000"
      }
    }
  ]
}
```

### 7. 管理エンドポイント

#### GET /admin/users
すべてのユーザーをリストする（管理者のみ）。

#### GET /admin/servers
すべてのサーバーをリストする（管理者のみ）。

#### GET /admin/system/info
システム情報を取得する。

**レスポンス (200 OK):**
```json
{
  "version": "2.0.0",
  "uptime_seconds": 86400,
  "database": {
    "type": "postgresql",
    "version": "15.4",
    "connection_pool": {
      "active": 5,
      "idle": 15,
      "max": 20
    }
  },
  "cache": {
    "type": "redis",
    "version": "7.0.5",
    "memory_usage_mb": 128,
    "hit_rate": 0.95
  },
  "statistics": {
    "total_users": 42,
    "active_users": 38,
    "total_servers": 156,
    "running_servers": 23,
    "total_backups": 1247,
    "total_backup_size_gb": 45.6
  },
  "health": {
    "database": "healthy",
    "cache": "healthy",
    "file_system": "healthy",
    "background_jobs": "healthy"
  }
}
```

#### POST /admin/system/sync
ファイルシステムとデータベースを同期する。

#### GET /admin/audit
監査ログを取得する。

#### GET /admin/metrics
システムメトリクスを取得する。

### 8. ジョブステータスエンドポイント

#### GET /jobs/{job_id}
ジョブステータスを取得する。

**レスポンス (200 OK):**
```json
{
  "id": "660e8400-e29b-41d4-a716-446655440000",
  "type": "server_start",
  "status": "completed",
  "progress": 100,
  "started_at": "2024-01-16T14:30:00Z",
  "completed_at": "2024-01-16T14:30:45Z",
  "duration_seconds": 45,
  "result": {
    "server_id": "550e8400-e29b-41d4-a716-446655440000",
    "final_status": "running",
    "process_id": 12345
  },
  "logs": [
    {
      "timestamp": "2024-01-16T14:30:15Z",
      "level": "INFO",
      "message": "サーバープロセスを開始中..."
    },
    {
      "timestamp": "2024-01-16T14:30:45Z",
      "level": "INFO",
      "message": "サーバーが正常に起動しました"
    }
  ]
}
```

## WebSocket API

### 接続エンドポイント

#### /ws/servers/{server_id}/status
リアルタイムサーバーステータス更新。

**接続メッセージ:**
```json
{
  "type": "connected",
  "server_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-16T14:30:00Z"
}
```

**ステータス更新メッセージ:**
```json
{
  "type": "status_update",
  "server_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "running",
  "metrics": {
    "cpu_usage_percent": 15.5,
    "memory_usage_mb": 3072,
    "player_count": 5,
    "tps": 19.8
  },
  "timestamp": "2024-01-16T14:30:30Z"
}
```

#### /ws/servers/{server_id}/logs
リアルタイムログストリーミング。

**ログメッセージ:**
```json
{
  "type": "log_line",
  "server_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-16T14:30:00Z",
  "level": "INFO",
  "thread": "Server thread",
  "message": "[Server] プレイヤーがゲームに参加しました",
  "raw_line": "[14:30:00] [Server thread/INFO]: [Server] プレイヤーがゲームに参加しました"
}
```

#### /ws/servers/{server_id}/console
インタラクティブコンソールセッション。

**コマンド送信:**
```json
{
  "type": "command",
  "command": "list",
  "correlation_id": "cmd_123"
}
```

**コマンドレスポンス:**
```json
{
  "type": "command_response",
  "correlation_id": "cmd_123",
  "command": "list",
  "response": "最大20人中5人のプレイヤーがオンライン: player1, player2, player3, player4, player5",
  "success": true,
  "timestamp": "2024-01-16T14:30:00Z"
}
```

#### /ws/notifications
グローバルユーザー通知。

**通知メッセージ:**
```json
{
  "type": "notification",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "category": "server",
  "title": "サーバー起動",
  "message": "あなたのサーバー 'survival-world' が正常に起動しました",
  "severity": "info",
  "data": {
    "server_id": "550e8400-e29b-41d4-a716-446655440000",
    "server_name": "survival-world"
  },
  "timestamp": "2024-01-16T14:30:00Z",
  "read": false,
  "_links": {
    "server": "/api/v2/servers/550e8400-e29b-41d4-a716-446655440000"
  }
}
```

## エラーハンドリング

### 標準エラーレスポンス形式
```json
{
  "error": {
    "type": "validation_error",
    "code": "INVALID_INPUT",
    "message": "リクエストの検証に失敗しました",
    "details": [
      {
        "field": "memory_mb",
        "message": "メモリは512MBから32768MBの間である必要があります",
        "value": 100
      }
    ],
    "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2024-01-16T14:30:00Z"
  },
  "_links": {
    "documentation": "/api/docs#error-codes"
  }
}
```

### HTTPステータスコード
- **200 OK**: 成功したGET、PUTリクエスト
- **201 Created**: 成功したPOSTリクエスト
- **202 Accepted**: 非同期操作の開始
- **204 No Content**: 成功したDELETEリクエスト
- **400 Bad Request**: 無効なリクエストデータ
- **401 Unauthorized**: 認証が必要
- **403 Forbidden**: 権限不足
- **404 Not Found**: リソースが見つからない
- **409 Conflict**: リソースの競合（例：ポートが使用中）
- **422 Unprocessable Entity**: バリデーションエラー
- **429 Too Many Requests**: レート制限超過
- **500 Internal Server Error**: サーバーエラー

### エラーコード
```python
class ErrorCodes:
    # 認証エラー
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    TOKEN_INVALID = "TOKEN_INVALID"
    ACCOUNT_NOT_APPROVED = "ACCOUNT_NOT_APPROVED"
    
    # 認可エラー
    INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"
    RESOURCE_NOT_OWNED = "RESOURCE_NOT_OWNED"
    
    # バリデーションエラー
    INVALID_INPUT = "INVALID_INPUT"
    REQUIRED_FIELD = "REQUIRED_FIELD"
    FIELD_TOO_LONG = "FIELD_TOO_LONG"
    INVALID_FORMAT = "INVALID_FORMAT"
    
    # リソースエラー
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_CONFLICT = "RESOURCE_CONFLICT"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    
    # サーバー管理エラー
    SERVER_NOT_RUNNING = "SERVER_NOT_RUNNING"
    SERVER_ALREADY_RUNNING = "SERVER_ALREADY_RUNNING"
    PORT_UNAVAILABLE = "PORT_UNAVAILABLE"
    INVALID_SERVER_TYPE = "INVALID_SERVER_TYPE"
    
    # システムエラー
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
```

## レート制限

### レート制限ヘッダー
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1640995200
X-RateLimit-Window: 60
```

### エンドポイントカテゴリ別レート制限
- **認証**: 5リクエスト/分
- **サーバーコントロール**: サーバーあたり10リクエスト/分
- **コンソールコマンド**: サーバーあたり30リクエスト/分
- **一般API**: 100リクエスト/分
- **ファイル操作**: サーバーあたり20リクエスト/分
- **WebSocket接続**: 1000メッセージ/分

## APIバージョニング

### URLバージョニング
- 現在のバージョン: `/api/v2/`
- 以前のバージョン: `/api/v1/`（廃止予定）

### バージョンヘッダー
```
API-Version: 2.0
API-Deprecated-Version: 1.0
API-Sunset-Date: 2024-12-31
```

### 後方互換性
- V1エンドポイントは2024-12-31まで対応
- V2エンドポイントは安定しており、維持される
- 破壊的変更はメジャーバージョンをインクリメント

## OpenAPI仕様

完全なOpenAPI 3.0仕様はFastAPIによって自動生成され、以下で利用可能：
- **Swagger UI**: `/api/docs`
- **ReDoc**: `/api/redoc`
- **OpenAPI JSON**: `/api/openapi.json`

### OpenAPIスニペット例
```yaml
openapi: 3.0.0
info:
  title: Minecraft Server Dashboard API V2
  version: 2.0.0
  description: 複数のMinecraftサーバーを管理するための包括的なAPI
  contact:
    name: APIサポート
    email: api-support@example.com
  license:
    name: MIT License
    url: https://opensource.org/licenses/MIT

servers:
  - url: https://api.mcserver.example.com/api/v2
    description: 本番サーバー
  - url: http://localhost:8000/api/v2
    description: 開発サーバー

components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT

  schemas:
    Server:
      type: object
      required:
        - name
        - minecraft_version
        - memory_mb
      properties:
        id:
          type: string
          format: uuid
          readOnly: true
        name:
          type: string
          minLength: 3
          maxLength: 50
          pattern: '^[a-zA-Z0-9_-]+$'
        description:
          type: string
          maxLength: 500
        status:
          type: string
          enum: [stopped, starting, running, stopping, crashed]
          readOnly: true
        port:
          type: integer
          minimum: 1024
          maximum: 65535
        minecraft_version:
          type: string
          pattern: '^\d+\.\d+(\.\d+)?$'
        memory_mb:
          type: integer
          minimum: 512
          maximum: 32768

paths:
  /servers:
    get:
      summary: サーバーをリストする
      tags: [Servers]
      security:
        - BearerAuth: []
      parameters:
        - name: page
          in: query
          schema:
            type: integer
            minimum: 1
            default: 1
        - name: limit
          in: query
          schema:
            type: integer
            minimum: 1
            maximum: 100
            default: 20
      responses:
        '200':
          description: サーバーリスト
          content:
            application/json:
              schema:
                type: object
                properties:
                  servers:
                    type: array
                    items:
                      $ref: '#/components/schemas/Server'
```

この包括的なAPI設計は、一貫したパターン、適切なエラーハンドリング、広範囲な機能カバレッジを持つMinecraft Server Dashboard API V2を実装するための完全な仕様を提供します。