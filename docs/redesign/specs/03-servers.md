# 仕様書: サーバー管理・制御・ユーティリティ

## データモデル

### Server

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| name | string(100) | NOT NULL | - | サーバー名 |
| description | text | - | NULL | 説明 |
| minecraft_version | string(20) | NOT NULL | - | 例: "1.20.1" |
| server_type | enum | NOT NULL | - | vanilla / forge / paper |
| status | enum | NOT NULL | stopped | stopped / starting / running / stopping / error |
| directory_path | string(500) | NOT NULL | - | サーバーディレクトリの絶対パス |
| port | int | NOT NULL | 25565 | 1024-65535 |
| max_memory | int | NOT NULL | 1024 | MB (512-16384) |
| max_players | int | NOT NULL | 20 | 1-100 |
| owner_id | int | FK(users.id), NOT NULL | - | 所有者 |
| template_id | int | FK(templates.id) | NULL | 適用テンプレート |
| is_deleted | bool | NOT NULL | false | 論理削除フラグ |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**ServerStatus:** stopped / starting / running / stopping / error

**ServerType:** vanilla / forge / paper

### ServerConfiguration

| フィールド | 型 | 制約 | 説明 |
|-----------|-----|------|------|
| id | int | PK | - |
| server_id | int | FK(servers.id), NOT NULL | - |
| configuration_key | string(100) | NOT NULL | キー名 |
| configuration_value | text | NOT NULL | 値 |
| updated_at | datetime(tz) | NOT NULL | - |

**UNIQUE 制約:** (server_id, configuration_key)

---

## サーバー管理エンドポイント

### POST /api/v1/servers — サーバー作成

**認証:** User

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字、命名規則あり | ○ |
| description | string | 最大 500 文字 | - |
| minecraft_version | string | 形式: X.Y または X.Y.Z、最小 1.8 | ○ |
| server_type | enum | vanilla / forge / paper | ○ |
| port | int | 1024-65535 | - (デフォルト 25565) |
| max_memory | int | 512-16384 | - (デフォルト 1024) |
| max_players | int | 1-100 | - (デフォルト 20) |
| template_id | int | - | - |
| server_properties | object | 許可キーのみ | - |
| attach_groups | object | `{op_groups: [id], whitelist_groups: [id]}` | - |

**server_properties の許可キー:** difficulty, gamemode, hardcore, pvp, spawn_protection, enable_command_block, allow_flight, spawn_monsters, spawn_animals, spawn_npcs, generate_structures, level_name, level_seed, level_type, motd, online_mode, white_list, enforce_whitelist, view_distance, simulation_distance, op_permission_level

**レスポンス (201):** `ServerResponse`

**処理フロー:**
1. サーバー名の一意性チェック (論理削除含めて除外)
2. Java 互換性検証 (指定 MC バージョンに対応する Java が利用可能か)
3. サーバーディレクトリを作成 (アトミック、ファイルロック使用)
4. サーバー JAR をダウンロード (キャッシュを優先利用)
5. DB レコード作成 (status=stopped)
6. 設定ファイル生成: server.properties / eula.txt / start.sh
7. テンプレートが指定された場合は適用
8. グループが指定された場合は attach
9. 失敗時はディレクトリをクリーンアップ

**エラー:**
- 409 `Server name already exists`
- 400 バージョン形式エラー / Java 互換性なし / プロパティ不正
- 500 ファイルシステムエラー / ダウンロード失敗

---

**サーバー名バリデーション:**
- 長さ: 1-100 文字
- パターン: 英数字で始まり・終わること。中間はスペース / ハイフン / アンダースコア / ドットを許容
- 禁止文字: `/ \ : * ? " < > |`
- Windows 予約名禁止: CON, PRN, AUX, NUL, COM1-9, LPT1-9
- `..` を含むパス traversal は禁止
- ドットやスペースで始まり・終わることは禁止

---

### GET /api/v1/servers — サーバー一覧

**認証:** User

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| page | int (≥1) | 1 |
| size | int (1-100) | 50 |

**レスポンス (200):**
```json
{
  "servers": [ ...ServerResponse[] ],
  "total": 100,
  "page": 1,
  "size": 50
}
```

**注意:** 論理削除済み (is_deleted=true) は除外。作成日時の降順。

---

### GET /api/v1/servers/{server_id} — サーバー詳細

**認証:** User

**レスポンス (200):** `ServerResponse`

**エラー:**
- 404 `Server not found`

---

### PUT /api/v1/servers/{server_id} — サーバー更新

**認証:** User

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | - | 任意 |
| description | string | - | 任意 |
| max_memory | int | 512-16384 | 任意 |
| max_players | int | 1-100 | 任意 |
| port | int | 1024-65535 | 任意 |
| server_properties | object | - | 任意 |

**重要:** `max_memory` または `server_properties` を更新する場合、サーバーは `stopped` または `error` 状態である必要がある。

**処理フロー:**
1. DB レコード更新
2. server.properties ファイルに変更を同期 (port, max-players 等)

**エラー:**
- 404 Not found
- 409 `Server not in required state for update`

---

### DELETE /api/v1/servers/{server_id} — サーバー削除

**認証:** Owner または Admin

**レスポンス (204):** 空

**処理フロー:**
1. 権限チェック: `user.role == admin OR server.owner_id == user.id`
2. 稼働中の場合は停止
3. 論理削除 (`is_deleted=true`, `status=stopped`)

**エラー:**
- 403 Not owner or admin
- 404 Not found

---

## サーバー制御エンドポイント

### POST /api/v1/servers/{server_id}/start — 起動

**認証:** User

**レスポンス (200):**
```json
{
  "server_id": 1,
  "status": "starting",
  "process_info": {
    "pid": 12345,
    "started_at": "ISO8601",
    "uptime_seconds": 0.5
  }
}
```

**起動前チェック (プリフライト):**
1. ステータスが `stopped` または `error` であること
2. DB と server.properties の双方向同期
3. ポートの利用可能確認 (稼働中サーバーとのバッティング + システムソケット確認)
4. Java 互換性確認 (指定 MC バージョンに対応する Java が見つかること)
5. server.jar ファイルの存在と読み取り権限確認
6. eula.txt に `eula=true` が含まれること
7. RCON 設定 (利用可能ポートを自動選択、ランダムパスワード生成、server.properties に書き込み)

**起動フロー:**
1. double-fork でデーモンプロセス作成
2. デーモン動作確認 (300ms にわたり 3 回確認)
3. PID ファイル書き込み
4. バックグラウンドでログ監視タスク + デーモン監視タスクを開始
5. DB ステータスを `starting` に更新

**デーモン監視:** ログに "Done" + "For help" / "Time elapsed" が出現したら `running` に遷移。タイムアウト: 45 秒。

**エラー:**
- 409 `Server not in valid state (not stopped/error)`
- 500 Java 不在 / JAR 欠損 / 起動失敗

---

### POST /api/v1/servers/{server_id}/stop — 停止

**認証:** User

**クエリパラメータ:**
| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|---------|------|
| force | bool | false | true: 強制終了 |

**レスポンス (200):**
```json
{ "message": "string" }
```

**停止フロー:**
1. force=false: stdin に `stop\n` を送信し最大 15 秒待機
2. 停止しない / force=true: SIGTERM を送信し最大 5 秒待機
3. さらに停止しない: SIGKILL
4. PID ファイルを削除
5. DB ステータスを `stopped` に更新

**エラー:**
- 409 `Server already stopped`

---

### POST /api/v1/servers/{server_id}/restart — 再起動

**認証:** User

**レスポンス (200):**
```json
{ "message": "string" }
```

**処理フロー:**
1. 稼働中の場合は停止 (指数バックオフで最大 60 秒待機)
2. 停止を確認後、起動フロー実行

**エラー:**
- 500 停止タイムアウト

---

### GET /api/v1/servers/{server_id}/status — 状態取得

**認証:** User

**レスポンス (200):**
```json
{
  "server_id": 1,
  "status": "stopped|starting|running|stopping|error",
  "process_info": {
    "pid": 12345,
    "started_at": "ISO8601",
    "uptime_seconds": 123.4
  }
}
```

---

### POST /api/v1/servers/{server_id}/command — コマンド送信

**認証:** User

**リクエスト:**
```json
{ "command": "string (1-500文字)" }
```

**禁止コマンド:** stop, restart, shutdown

**処理フロー:**
1. サーバーが `running` 状態であること
2. RCON が利用可能な場合 → RCON 経由で送信
3. RCON 不可の場合 → stdin に書き込み
4. 監査ログ記録

**エラー:**
- 409 Server not running
- 400 危険なコマンド

---

### GET /api/v1/servers/{server_id}/logs — ログ取得

**認証:** User

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| lines | int (1-1000) | 100 |

**レスポンス (200):**
```json
{
  "server_id": 1,
  "logs": ["string", "..."],
  "total_lines": 50
}
```

---

## ユーティリティエンドポイント

### GET /api/v1/servers/versions/supported — サポートバージョン一覧

**認証:** 不要

**レスポンス (200):**
```json
{
  "versions": [
    {
      "version": "1.20.1",
      "server_type": "vanilla|forge|paper",
      "download_url": "string",
      "is_supported": true,
      "release_date": "ISO8601|null",
      "is_stable": true,
      "build_number": null
    }
  ]
}
```

**実装詳細:** DB から取得 (10-50ms)。外部 API には問い合わせない。

---

### POST /api/v1/servers/sync — サーバー状態同期

**認証:** Admin

**レスポンス (200):**
```json
{
  "message": "string",
  "running_servers": [1, 2, 3],
  "total_running": 3
}
```

**処理フロー:**
1. サーバーディレクトリの PID ファイルをスキャン
2. 生存確認 (psutil 等でプロセス存在を確認)
3. DB のステータスを実際のプロセス状態と同期

---

### GET /api/v1/servers/cache/stats — JAR キャッシュ統計

**認証:** Admin

**レスポンス (200):**
```json
{
  "total_files": 10,
  "total_size_mb": 512.5,
  "cache_dir": "string",
  "max_age_days": 30,
  "max_size_gb": 10
}
```

---

### POST /api/v1/servers/cache/cleanup — JAR キャッシュクリーンアップ

**認証:** Admin

**処理フロー:**
1. 30 日以上経過したファイルを削除
2. 合計サイズが 10GB を超える場合は古いものから削除

---

### GET /api/v1/servers/java/compatibility — Java 互換情報

**認証:** 不要

**レスポンス (200):**
```json
{
  "java_installations_found": 2,
  "compatibility_matrix": {
    "1.8.0 - 1.16.5": 8,
    "1.17.0 - 1.17.1": 16,
    "1.18.0 - 1.20.9": 17,
    "1.21.0+": 21
  },
  "installations": {
    "17": {
      "major_version": 17,
      "version_string": "17.0.8",
      "vendor": "OpenJDK",
      "executable_path": "/usr/bin/java",
      "supported_minecraft_versions": ["1.18 - 1.20.9"]
    }
  },
  "error": null,
  "installation_help": null
}
```

**Java 互換性マトリクス:**
| Minecraft バージョン | 必要 Java |
|---------------------|---------|
| 1.8.0 - 1.16.5 | Java 8 |
| 1.17.0 - 1.17.1 | Java 16 |
| 1.18.0 - 1.20.9 | Java 17 |
| 1.21.0+ | Java 21 |

---

### GET /api/v1/servers/java/validate/{minecraft_version} — Java 互換確認

**認証:** 不要

**レスポンス (200):**
```json
{
  "compatible": true,
  "minecraft_version": "1.20.1",
  "required_java": 17,
  "available_java_versions": [8, 17, 21],
  "selected_java": {
    "major_version": 17,
    "version_string": "17.0.8",
    "vendor": "OpenJDK",
    "executable_path": "/usr/bin/java"
  },
  "message": "string",
  "error": null,
  "installation_help": null
}
```

**エラー:**
- 400 バージョン形式不正

---

## インポート/エクスポート

### GET /api/v1/servers/{server_id}/export — エクスポート

**認証:** User

**レスポンス:** ZIP ファイルダウンロード (application/zip)

**ZIP 内容:**
- `export_metadata.json`: サーバー設定情報
- サーバーファイル (除外: *.log, logs/, crash-reports/, *.tmp, .DS_Store, Thumbs.db)

**エラー:**
- 404 Server or directory not found

---

### POST /api/v1/servers/import — インポート

**認証:** Operator または Admin

**リクエスト (multipart/form-data):**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| name | string (1-100) | ○ |
| description | string | - |
| file | UploadFile (ZIP) | ○ |

**制約:** ファイルサイズ最大 500MB

**処理フロー:**
1. ZIP 形式の確認
2. `export_metadata.json` の存在確認と必須フィールド検証
3. 空きポートを自動で検索
4. サーバーを作成 (create_server ロジックを使用)
5. 展開したファイルでサーバーディレクトリを上書き
6. metadata ファイルを削除

**エラー:**
- 403 Not operator/admin
- 400 Invalid ZIP / missing metadata
- 413 File > 500MB

---

## サーバー起動のデーモンプロセス (Double-Fork)

```
API プロセス (親)
 └─ Fork #1 (中間プロセス)
     ├─ setsid() — 新セッションのリーダーになる
     ├─ umask(0)
     └─ Fork #2 (デーモン本体)
         ├─ stdin → /dev/null
         ├─ stdout → server.log
         ├─ stderr → server_error.log
         └─ execvpe() — Java プロセスになる

PID ファイル (minecraft_server.pid) に保存される情報:
{
  "pid": 12345,
  "server_id": 1,
  "port": 25565,
  "rcon_port": 25575,
  "rcon_password": "...",
  "cmd": ["java", "-Xmx1024M", "-jar", "server.jar"],
  "created_at": "ISO8601"
}
```

API 再起動時: PID ファイルをスキャンし、プロセスが生存していれば状態を復元する。
