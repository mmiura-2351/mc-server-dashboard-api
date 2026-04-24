# 仕様書: バックアップ管理 / スケジューラー

## データモデル

### Backup

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| server_id | int | FK(servers.id), NOT NULL | - | - |
| name | string(100) | NOT NULL | - | バックアップ名 |
| description | string(500) | - | NULL | - |
| file_path | string(500) | NOT NULL | - | tar.gz の絶対パス |
| file_size | bigint | NOT NULL | - | バイト数 |
| backup_type | enum | NOT NULL | manual | manual / scheduled / pre_update |
| status | enum | NOT NULL | creating | creating / completed / failed |
| created_at | datetime | NOT NULL | utcnow() | - |

### BackupSchedule

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| server_id | int | FK(servers.id), UNIQUE, NOT NULL | - | サーバー毎に 1 つ |
| interval_hours | int | NOT NULL, CHECK 1-168 | - | 実行間隔 (時間) |
| max_backups | int | NOT NULL, CHECK 1-30 | - | 保持する最大バックアップ数 |
| enabled | bool | NOT NULL | true | スケジュール有効フラグ |
| only_when_running | bool | NOT NULL | true | 稼働中のみバックアップ |
| last_backup_at | datetime | - | NULL | 最終バックアップ日時 |
| next_backup_at | datetime | - | NULL | 次回実行予定日時 |
| created_at | datetime | NOT NULL | utcnow() | - |
| updated_at | datetime | NOT NULL | utcnow() | - |

### BackupScheduleLog

| フィールド | 型 | 制約 | 説明 |
|-----------|-----|------|------|
| id | int | PK | - |
| server_id | int | FK(servers.id), NOT NULL | - |
| action | enum | NOT NULL | created / updated / deleted / executed / skipped |
| reason | string(255) | - | スキップ/失敗の理由 |
| old_config | JSON | - | 変更前の設定 |
| new_config | JSON | - | 変更後の設定 |
| executed_by_user_id | int | FK(users.id) | - |
| created_at | datetime | NOT NULL | - |

---

## バックアップエンドポイント

### POST /servers/{server_id}/backups — バックアップ作成

**認証:** User

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字、禁止文字: `/\:*?"<>|` | ○ |
| description | string | 最大 500 文字 | - |
| backup_type | enum | manual / scheduled / pre_update | - (デフォルト manual) |

**レスポンス (201):** `BackupResponse`
```json
{
  "id": 1,
  "server_id": 1,
  "name": "string",
  "description": "string|null",
  "file_path": "string",
  "file_size": 10485760,
  "file_size_mb": 10.0,
  "backup_type": "manual",
  "status": "completed",
  "created_at": "ISO8601",
  "server_name": "string",
  "minecraft_version": "1.20.1"
}
```

**処理フロー:**
1. サーバーアクセス権確認
2. `status=creating` でレコード作成
3. サーバーディレクトリを tar.gz で圧縮
4. ファイルパス・サイズで更新、`status=completed`

---

### POST /servers/{server_id}/backups/upload — バックアップアップロード

**認証:** User

**リクエスト (multipart/form-data):**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| file | UploadFile (.tar.gz / .tgz) | ○ |
| name | string | - |
| description | string | - |

**制約:** Content-Length ≤ 500MB

**処理フロー:**
1. Content-Length 確認
2. ファイル形式確認 (tar.gz / tgz)
3. 一時ファイルにストリーミング保存 (メモリ監視付き)
4. アーカイブの安全性検証 (パストラバーサル等)
5. バックアップディレクトリに移動
6. `status=completed` でレコード作成

**エラー:**
- 400 No file / invalid format
- 413 File > 500MB

---

### GET /servers/{server_id}/backups — サーバーバックアップ一覧

**認証:** User

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| page | int (≥1) | 1 |
| size | int (1-100) | 50 |
| backup_type | enum | 任意 |

**レスポンス (200):** ページネーション付き `BackupListResponse`

---

### GET /backups — 全バックアップ一覧 (Admin)

**認証:** Admin

**クエリパラメータ:** 上記と同じ

---

### GET /backups/statistics — バックアップ統計 (全体)

**認証:** Admin

**レスポンス (200):**
```json
{
  "total_backups": 100,
  "completed_backups": 95,
  "failed_backups": 5,
  "total_size_bytes": 1073741824,
  "total_size_mb": 1024.0
}
```

---

### GET /servers/{server_id}/backups/statistics — バックアップ統計 (サーバー単位)

**認証:** User

**レスポンス (200):** 上記と同じ形式

---

### GET /backups/{backup_id} — バックアップ詳細

**認証:** User

**レスポンス (200):** `BackupResponse`

**エラー:**
- 404 Backup not found

---

### POST /backups/{backup_id}/restore — バックアップ復元

**認証:** User

**リクエスト:**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| target_server_id | int | 任意 (省略時は元サーバー) |
| confirm | bool | ○ (true 必須) |

**レスポンス (200):**
```json
{
  "success": true,
  "message": "string",
  "backup_id": 1,
  "details": {}
}
```

**処理フロー:**
1. バックアップの `status=completed` を確認
2. 対象サーバーが `stopped` 状態であること
3. 現在の状態を事前にバックアップ (pre_update タイプ)
4. tar.gz を展開してサーバーディレクトリに上書き

**エラー:**
- 400 Backup not completed / Server not stopped
- 404 Backup / Server not found

---

### POST /backups/{backup_id}/restore-with-template — バックアップ復元 + テンプレート生成

**認証:** User

**リクエスト:**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| target_server_id | int | 任意 |
| confirm | bool | ○ |
| template_name | string (1-100) | ○ |
| template_description | string (max 500) | - |
| is_public | bool | - (デフォルト false) |

**レスポンス (200):**
```json
{
  "backup_restored": true,
  "template_created": true,
  "message": "string",
  "backup_id": 1,
  "template_id": 5,
  "template_name": "string"
}
```

---

### GET /backups/{backup_id}/download — バックアップダウンロード

**認証:** User

**レスポンス (200):** バイナリストリーム (application/gzip)

**ファイル名形式:** `{server_name}_{backup_name}_{backup_id}.tar.gz`

**エラー:**
- 400 Backup not completed
- 404 File not found on disk

---

### DELETE /backups/{backup_id} — バックアップ削除

**認証:** Owner または Admin

**レスポンス (204):** 空

**処理フロー:**
1. 権限確認: `user.role == admin OR server.owner_id == user.id`
2. ディスクからファイルを削除
3. DB レコードを削除

---

### POST /backups/scheduled — 複数サーバーの手動スケジュールバックアップ (Admin)

**認証:** Admin

**リクエスト:**
```json
{ "server_ids": [1, 2, 3] }
```

**制約:** server_ids は空でない、重複なし

**レスポンス (200):**
```json
{
  "success": true,
  "message": "string",
  "details": {
    "created_backups": [1, 2],
    "failed_servers": [3],
    "total_requested": 3,
    "total_created": 2
  }
}
```

---

## バックアップスケジューラーエンドポイント

### POST /scheduler/servers/{server_id}/schedule — スケジュール作成

**認証:** User

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| interval_hours | int | 1-168 | ○ |
| max_backups | int | 1-30 | ○ |
| enabled | bool | - | - (デフォルト true) |
| only_when_running | bool | - | - (デフォルト true) |

**レスポンス (201):** `BackupScheduleResponse`
```json
{
  "id": 1,
  "server_id": 1,
  "interval_hours": 24,
  "max_backups": 10,
  "enabled": true,
  "only_when_running": true,
  "last_backup_at": null,
  "next_backup_at": "ISO8601",
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

**処理フロー:**
1. サーバー毎のスケジュールは 1 つのみ (重複チェック)
2. `next_backup_at = now + interval_hours` を計算
3. ログ記録 (ScheduleAction.created)

**エラー:**
- 409 Schedule already exists for server

---

### GET /scheduler/servers/{server_id}/schedule — スケジュール取得

**認証:** User

**レスポンス (200):** `BackupScheduleResponse`

---

### PUT /scheduler/servers/{server_id}/schedule — スケジュール更新

**認証:** User

**リクエスト:** (すべて任意)
```json
{
  "interval_hours": 12,
  "max_backups": 5,
  "enabled": true,
  "only_when_running": false
}
```

**処理フロー:**
1. 変更フィールドのみ更新
2. interval_hours が変更された場合は next_backup_at を再計算
3. ログ記録 (old_config / new_config 付き)

---

### DELETE /scheduler/servers/{server_id}/schedule — スケジュール削除

**認証:** User

**レスポンス (204):** 空

---

### GET /scheduler/servers/{server_id}/logs — スケジュールログ取得

**認証:** User

**クエリパラメータ:** page, size

**レスポンス (200):** `List[BackupScheduleLogResponse]`
```json
[
  {
    "id": 1,
    "server_id": 1,
    "action": "created|updated|deleted|executed|skipped",
    "reason": "string|null",
    "old_config": null,
    "new_config": null,
    "executed_by_user_id": 1,
    "executed_by_username": "string",
    "created_at": "ISO8601"
  }
]
```

---

### GET /scheduler/status — スケジューラー全体状態 (Admin)

**認証:** Admin

**レスポンス (200):**
```json
{
  "is_running": true,
  "total_schedules": 10,
  "enabled_schedules": 8,
  "cache_size": 10,
  "next_execution": "ISO8601"
}
```

---

### GET /scheduler/schedules — 全スケジュール一覧 (Admin)

**認証:** Admin

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| enabled_only | bool | false |

**レスポンス (200):** `List[BackupScheduleResponse]`

---

## スケジューラー動作仕様

- **チェック間隔:** 10 分ごと
- **実行条件:** `enabled=true` AND `next_backup_at <= now(UTC)`
- **only_when_running=true の場合:** サーバーが `running` 状態のときのみ実行
- **実行後:** `last_backup_at` と `next_backup_at` を更新
- **max_backups 超過時:** 最も古い scheduled / pre_update バックアップを削除
- **スケジューラーキャッシュ:** メモリにスケジュールをキャッシュし、DB との同期を維持

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| バックアップ名 | 1-100 文字、禁止文字: `/\:*?"<>|` |
| 説明 | 最大 500 文字 |
| interval_hours | 1-168 (1時間〜1週間) |
| max_backups | 1-30 |
| ファイルサイズ上限 | 500MB (アップロード時) |
