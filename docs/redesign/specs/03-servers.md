# 仕様書: サーバー管理・制御

## 設計原則

- **すべてのライフサイクル操作は非同期ジョブ。** 起動/停止/作成/削除はすべて Job を返す
- **Runner 抽象化。** サーバーの実行基盤（ホストプロセス/Docker/Podman/VM 等）は差し替え可能なプラグイン構造とし、API Core は Runner の実装に依存しない
- **設定の責務分離。** DB はインフラ設定（コンテナ起動に必要な情報）のみ保持し、ゲーム設定（server.properties の内容）はファイルが唯一の真実の源
- **Organization スコープ。** サーバーは Organization に属し、他の Organization からは不可視
- **ドメイン接続対応。** slug フィールドで DNS フレンドリーな名前を確保し、将来のドメインベース接続（SRV レコード / Minecraft プロキシ等）に備える

---

## データモデル

### Server

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| organization_id | UUID | FK(organizations.id), NOT NULL | - | 所属 Organization |
| name | string(100) | NOT NULL | - | 表示名 |
| slug | string(50) | NOT NULL | - | DNS フレンドリーな識別子 |
| description | text | - | NULL | - |
| minecraft_version | string(20) | NOT NULL | - | 例: "1.21.1" |
| server_type | enum | NOT NULL | - | vanilla / paper / spigot / purpur / forge / fabric / neoforge / folia |
| status | enum | NOT NULL | creating | 下記参照 |
| runner_type | enum | NOT NULL | - | host / docker / podman (Runner プラグイン種別) |
| runner_instance_id | string(255) | - | NULL | Runner が管理するインスタンス識別子 (コンテナID等) |
| max_memory_mb | int | NOT NULL | 2048 | JVM ヒープ上限 (MB) |
| max_cpu_cores | float | NOT NULL | 1.0 | CPU 上限 (コア数) |
| max_disk_gb | int | NOT NULL | 20 | ディスククォータ (GB) |
| connection_host | string(255) | - | NULL | 稼働中に Runner が設定する接続先ホスト |
| connection_port | int | - | NULL | 稼働中に Runner が割り当てた外部ポート |
| template_id | UUID | FK(templates.id), ON DELETE SET NULL | NULL | 作成時に適用したテンプレート |
| deleted_at | datetime(tz) | - | NULL | 論理削除日時 |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**UNIQUE 制約:** (organization_id, slug)

**ServerType:**

| 値 | 説明 |
|----|------|
| `vanilla` | Mojang 公式 |
| `paper` | PaperMC (高性能、最も一般的) |
| `folia` | PaperMC fork (領域マルチスレッド) |
| `spigot` | SpigotMC |
| `purpur` | Purpur fork |
| `forge` | MinecraftForge (Mod対応) |
| `fabric` | FabricMC (Mod対応) |
| `neoforge` | NeoForge (Forge 後継) |

---

### ServerStatus (状態遷移)

```
                    ┌─────────┐
             作成Job ↓         │ 作成失敗
            creating ──────→ error ←──┐
                │                    │  操作失敗
                │ 作成完了            │
                ↓                    │
┌─────────── stopped ────────────────┘
│               │ ↑
│ 削除Job        │ stop完了 / force-stop完了
↓               │
deleting   starting ←── stop完了後に再起動
(終端)         │ ↑
               │ │ 起動完了
               ↓ │
             running ──→ stopping ──→ stopped
               │            ↑
               └─ restarting ┘
                   (再起動Job)

restore Job: stopped → restoring → stopped
```

| status | 意味 |
|--------|------|
| `creating` | 初回作成 Job 実行中 (JAR DL・ディレクトリ構成) |
| `stopped` | 停止中 (操作可能な安定状態) |
| `starting` | 起動 Job 実行中 |
| `running` | 稼働中 |
| `stopping` | 停止 Job 実行中 |
| `restarting` | 再起動 Job 実行中 |
| `restoring` | バックアップ復元 Job 実行中 |
| `error` | 直前の操作が失敗 |
| `deleting` | 削除 Job 実行中 |

---

### Runner 抽象化

Runner は以下のインターフェースを実装するプラグインとして扱う。
API Core は Runner の実装詳細を知らず、このインターフェース経由でのみ制御する。

```
Runner Interface:
  - create(server_config) → runner_instance_id
  - start(runner_instance_id) → connection_host, connection_port
  - stop(runner_instance_id, force: bool)
  - restart(runner_instance_id)
  - delete(runner_instance_id)
  - exec_command(runner_instance_id, command) → output
  - get_logs(runner_instance_id, lines) → log_lines[]
  - get_status(runner_instance_id) → status
```

初期提供 Runner: `docker` / `podman` / `host` (直接プロセス起動)

---

## Job レスポンス

ライフサイクル操作は 202 Accepted でジョブ情報を返す。

```json
{
  "job_id": "uuid",
  "server_id": "uuid",
  "type": "server_create | server_start | server_stop | server_restart | server_delete | server_restore",
  "status": "queued | running | succeeded | failed | cancelled",
  "created_at": "ISO8601",
  "started_at": "ISO8601 | null",
  "completed_at": "ISO8601 | null",
  "error": "string | null"
}
```

Job の詳細仕様はジョブ管理仕様書に委ねる。

---

## ServerResponse

```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "name": "サバイバルサーバー",
  "slug": "survival",
  "description": "string | null",
  "minecraft_version": "1.21.1",
  "server_type": "paper",
  "status": "running",
  "runner_type": "docker",
  "settings": {
    "max_memory_mb": 4096,
    "max_cpu_cores": 2.0,
    "max_disk_gb": 50
  },
  "connection": {
    "host": "mc.example.com",
    "port": 25566
  },
  "template_id": "uuid | null",
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

`connection` は `status=running` のときのみ値を持つ。それ以外は `null`。

---

## エンドポイント

### POST /api/v2/organizations/{org_id}/servers — サーバー作成

**認証:** `server.create` 権限

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字 | ○ |
| slug | string | 1-50 文字、英小文字/数字/ハイフン、先頭末尾は英数字 | ○ |
| description | string | 最大 500 文字 | - |
| minecraft_version | string | `\d+\.\d+(\.\d+)?`、旧形式は最小 1.8 / 新形式 (25.x 以降) はすべて有効 | ○ |
| server_type | enum | - | ○ |
| runner_type | enum | - | ○ |
| max_memory_mb | int | 512-32768 | - (デフォルト 2048) |
| max_cpu_cores | float | 0.5-32.0 | - (デフォルト 1.0) |
| max_disk_gb | int | 5-1000 | - (デフォルト 20) |
| template_id | UUID | - | - |
| initial_groups | object | `{op_groups: [uuid], whitelist_groups: [uuid]}` | - |

**レスポンス (202):**
```json
{
  "server": { ...ServerResponse (status=creating) },
  "job": { ...JobResponse (type=server_create) }
}
```

**処理フロー:**
1. slug の一意性確認 (Organization 内) → 重複なら 409
2. minecraft_version が既知のバージョンか確認 → 不明なら 400
3. Server レコード作成 (`status=creating`)
4. `server_create` ジョブをキューに追加
5. ジョブが非同期で実行:
   a. Runner に作成を依頼 (JAR DL、ディレクトリ構成、eula.txt 生成)
   b. テンプレートが指定された場合は適用
   c. グループが指定された場合は attach
   d. 成功 → `status=stopped`、失敗 → `status=error`

**エラー:**
- 409 `Slug already exists in this organization`
- 400 `Unknown minecraft version`
- 422 バリデーションエラー

---

### GET /api/v2/organizations/{org_id}/servers — サーバー一覧

**認証:** `server.read` 権限

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| status | enum | フィルタ |
| server_type | enum | フィルタ |
| page | int | デフォルト 1 |
| page_size | int (1-100) | デフォルト 50 |

**レスポンス (200):**
```json
{
  "servers": [ ...ServerResponse[] ],
  "total_count": 10,
  "page": 1,
  "page_size": 50
}
```

論理削除済み (`deleted_at IS NOT NULL`) は除外。

---

### GET /api/v2/organizations/{org_id}/servers/{server_id} — サーバー詳細

**認証:** `server.read` 権限

**レスポンス (200):** `ServerResponse`

**エラー:**
- 404 `Server not found`

---

### PUT /api/v2/organizations/{org_id}/servers/{server_id} — メタデータ更新

**認証:** `server.settings.manage` 権限

**変更可能なフィールド (すべて任意):**
| フィールド | 型 | 制約 |
|-----------|-----|------|
| name | string | 1-100 文字 |
| slug | string | 1-50 文字、形式制約あり |
| description | string | 最大 500 文字 |

**Note:** `name` / `slug` / `description` は稼働中でも変更可能。

**レスポンス (200):** `ServerResponse`

**エラー:**
- 409 slug 重複
- 404 Not found

---

### PUT /api/v2/organizations/{org_id}/servers/{server_id}/settings — インフラ設定更新

**認証:** `server.settings.manage` 権限

**前提条件:** `status` が `stopped` または `error` であること

**リクエスト (JSON):** (すべて任意)
```json
{
  "max_memory_mb": 4096,
  "max_cpu_cores": 2.0,
  "max_disk_gb": 50
}
```

**レスポンス (200):** `ServerResponse`

**エラー:**
- 409 `Server must be stopped to change settings`

---

### DELETE /api/v2/organizations/{org_id}/servers/{server_id} — サーバー削除

**認証:** `server.delete` 権限

**前提条件:** `status` が `stopped` または `error` であること

**レスポンス (202):**
```json
{
  "job": { ...JobResponse (type=server_delete) }
}
```

**処理フロー (ジョブ内):**
1. Runner にインスタンス削除を依頼 (ファイル・コンテナ等の破棄)
2. Server を論理削除 (`deleted_at = now()`, `status=deleting` → 完了後レコードは削除済みとして参照不可)
3. 監査ログ記録

**エラー:**
- 409 `Server must be stopped before deletion`

---

## ライフサイクル制御エンドポイント

### POST /api/v2/organizations/{org_id}/servers/{server_id}/start — 起動

**認証:** `server.start` 権限

**前提条件:** `status` が `stopped` または `error`

**レスポンス (202):** `JobResponse (type=server_start)`

**ジョブ内処理:**
1. Runner にコンテナ/プロセス起動を依頼
2. Runner がポートを自動割り当て
3. Runner がログを監視し "Done" を検出 → `status=running`、`connection_host/port` を保存
4. タイムアウト (90秒) → `status=error`

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/stop — 停止

**認証:** `server.stop` 権限

**前提条件:** `status` が `running`

**レスポンス (202):** `JobResponse (type=server_stop)`

**ジョブ内処理:**
1. Runner 経由でグレースフルシャットダウン (`stop` コマンド送信)
2. 最大 30 秒待機
3. タイムアウト → 強制終了 (SIGKILL 相当)
4. `status=stopped`、`connection_host/port` を null に更新

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/force-stop — 強制停止

**認証:** `server.stop` 権限

**前提条件:** `status` が `running` / `starting` / `stopping`

**レスポンス (202):** `JobResponse (type=server_stop)`

**ジョブ内処理:** 即時強制終了 → `status=stopped`

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/restart — 再起動

**認証:** `server.start` 権限 + `server.stop` 権限

**前提条件:** `status` が `running`

**レスポンス (202):** `JobResponse (type=server_restart)`

**ジョブ内処理:** グレースフルシャットダウン → 起動 → running 確認

---

## コマンドエンドポイント

### POST /api/v2/organizations/{org_id}/servers/{server_id}/command — コマンド送信

**認証:** `server.command` 権限

**前提条件:** `status` が `running`

**リクエスト (JSON):**
```json
{ "command": "string (1-500文字)" }
```

**禁止コマンド:** `stop`, `restart`, `shutdown` (ライフサイクル API 経由で操作する)

**レスポンス (200):**
```json
{
  "command": "say Hello",
  "executed_at": "ISO8601"
}
```

**処理フロー:**
1. Runner の RCON インターフェース経由でコマンドを送信
2. 監査ログ記録

**エラー:**
- 409 `Server is not running`
- 400 `Command not allowed`

---

## ログエンドポイント

### GET /api/v2/organizations/{org_id}/servers/{server_id}/logs — ログ取得 (スナップショット)

**認証:** `server.read` 権限

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| lines | int (1-5000) | 200 |

**レスポンス (200):**
```json
{
  "server_id": "uuid",
  "lines": ["[12:00:00] [Server thread/INFO]: Done (3.456s)!"],
  "total_lines": 200,
  "retrieved_at": "ISO8601"
}
```

**Note:** リアルタイムログ配信は WebSocket 仕様 (08-realtime) を参照。

---

## ジョブエンドポイント

### GET /api/v2/organizations/{org_id}/servers/{server_id}/jobs — ジョブ履歴

**認証:** `server.read` 権限

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| type | enum | フィルタ |
| status | enum | フィルタ |
| page | int | デフォルト 1 |
| page_size | int (1-100) | デフォルト 20 |

**レスポンス (200):**
```json
{
  "jobs": [ ...JobResponse[] ],
  "total_count": 50
}
```

---

### GET /api/v2/organizations/{org_id}/servers/{server_id}/jobs/{job_id} — ジョブ詳細

**認証:** `server.read` 権限

**レスポンス (200):** `JobResponse`

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/jobs/{job_id}/cancel — ジョブキャンセル

**認証:** `server.settings.manage` 権限

**前提条件:** ジョブ `status` が `queued`

**レスポンス (200):** キャンセル後の `JobResponse`

**エラー:**
- 409 `Job is already running or completed`

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/jobs/{job_id}/retry — ジョブリトライ

**認証:** `server.settings.manage` 権限

**前提条件:** ジョブ `status` が `failed`

**レスポンス (202):** 新規 `JobResponse`

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| name | 1-100 文字 |
| slug | 1-50 文字、英小文字/数字/ハイフンのみ、先頭末尾は英数字、Organization 内一意 |
| description | 最大 500 文字 |
| minecraft_version | `\d+\.\d+(\.\d+)?`、既知のバージョンであること、旧形式は最小 1.8 / 新形式 (25.x 以降) はすべて有効 |
| server_type | 定義済み enum 値 |
| runner_type | 定義済み enum 値 |
| max_memory_mb | 512-32768 |
| max_cpu_cores | 0.5-32.0 |
| max_disk_gb | 5-1000 |
| command | 1-500 文字、禁止コマンドを含まない |
| logs.lines | 1-5000 |

---

## 状態遷移バリデーション

| 操作 | 許可される status |
|------|-----------------|
| start | `stopped`, `error` |
| stop | `running` |
| force-stop | `running`, `starting`, `stopping` |
| restart | `running` |
| settings update | `stopped`, `error` |
| delete | `stopped`, `error` |
| command | `running` |

---

## 監査イベント一覧

| イベント | action 値 | resource_type |
|--------|-----------|---------------|
| サーバー作成 Job 開始 | `server_create` | server |
| サーバー起動 Job 開始 | `server_start` | server |
| サーバー停止 Job 開始 | `server_stop` | server |
| サーバー強制停止 Job 開始 | `server_force_stop` | server |
| サーバー再起動 Job 開始 | `server_restart` | server |
| サーバー削除 Job 開始 | `server_delete` | server |
| メタデータ更新 | `server_update` | server |
| インフラ設定更新 | `server_settings_update` | server |
| コマンド送信 | `server_command` | server |
