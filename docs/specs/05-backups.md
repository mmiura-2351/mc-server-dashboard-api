# 仕様書: バックアップ管理 / スケジューラー

## 設計方針

- **バックアップ作成・復元は非同期ジョブ。** 圧縮/転送に時間がかかるため 202 + job_id を返す
- **ストレージ抽象化。** ローカルファイルシステムと S3 互換オブジェクトストレージの両方に対応し、バックエンドは設定で切り替え可能
- **スケジュール時刻指定。** interval_hours ではなく時刻ベースのスケジュール式で設定する。記法の詳細は別途定義（アプリケーション側で複雑さを吸収し、ユーザーはシンプルな指定ができる）
- **Organization スコープ。** バックアップはサーバー（= Organization）に属し、他の Organization からは不可視

---

## データモデル

### Backup

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| server_id | UUID | FK(servers.id), NOT NULL | - | - |
| name | string(100) | NOT NULL | - | バックアップ名 |
| description | string(500) | - | NULL | - |
| backup_type | enum | NOT NULL | manual | manual / scheduled / pre_restore |
| status | enum | NOT NULL | creating | creating / completed / failed |
| storage_backend | enum | NOT NULL | - | local / s3_compatible |
| storage_key | string(1000) | NOT NULL | - | ストレージ上の識別キー (ローカルはパス、S3はオブジェクトキー) |
| file_size_bytes | bigint | - | NULL | バイト数 (completed 後に設定) |
| created_by_user_id | UUID | FK(users.id), ON DELETE SET NULL | NULL | 作成者 (スケジュール実行時は NULL) |
| created_at | datetime(tz) | NOT NULL | now() | - |

**backup_type:**
- `manual` — ユーザーが手動で作成
- `scheduled` — スケジューラーが自動作成
- `pre_restore` — 復元前の自動スナップショット

---

### BackupSchedule

サーバーごとに 1 つだけ持てる自動バックアップスケジュール。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| server_id | UUID | FK(servers.id), UNIQUE, NOT NULL | - | サーバーごとに 1 つ |
| schedule_expression | string(100) | NOT NULL | - | スケジュール式 (形式は別途定義) |
| timezone | string(50) | NOT NULL | UTC | スケジュール解釈に使うタイムゾーン |
| max_backups | int | NOT NULL, CHECK(1-100) | 10 | 保持する最大バックアップ数 |
| enabled | bool | NOT NULL | true | スケジュール有効フラグ |
| only_when_running | bool | NOT NULL | true | サーバー稼働中のみ実行 |
| last_backup_at | datetime(tz) | - | NULL | 最終バックアップ実行日時 |
| next_backup_at | datetime(tz) | - | NULL | 次回実行予定日時 (schedule_expression から算出) |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**schedule_expression の例 (記法は別途定義):**
- 毎日午前3時にバックアップ
- 6時間ごとにバックアップ
- 毎週月曜の午前2時にバックアップ

---

### BackupScheduleLog

スケジュール設定変更・実行履歴。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| server_id | UUID | FK(servers.id), NOT NULL | - | - |
| action | enum | NOT NULL | - | created / updated / deleted / executed / skipped |
| reason | string(255) | - | NULL | スキップ/失敗の理由 |
| old_config | JSON | - | NULL | 変更前の設定 (updated 時のみ) |
| new_config | JSON | - | NULL | 変更後の設定 (created / updated 時のみ) |
| executed_by_user_id | UUID | FK(users.id), ON DELETE SET NULL | NULL | 操作者 (scheduled 実行時は NULL) |
| created_at | datetime(tz) | NOT NULL | now() | - |

---

## ストレージバックエンド

バックアップファイルの保存先は設定で切り替え可能な抽象化レイヤーを持つ。

| backend | 説明 | storage_key の形式 |
|---------|------|-------------------|
| `local` | API Core サーバーのローカルディレクトリ | `/backups/{org_id}/{server_id}/{uuid}.tar.gz` |
| `s3_compatible` | S3 互換オブジェクトストレージ (AWS S3 / MinIO 等) | `{bucket}/{org_id}/{server_id}/{uuid}.tar.gz` |

ストレージバックエンドの設定（認証情報・エンドポイント等）は環境変数で管理し、API Core が抽象化して扱う。Organization ごとに異なるバックエンドを設定することは MVP では対象外。

---

## BackupResponse

```json
{
  "id": "uuid",
  "server_id": "uuid",
  "server_name": "string",
  "name": "daily-2026-04-24",
  "description": "string | null",
  "backup_type": "manual | scheduled | pre_restore",
  "status": "creating | completed | failed",
  "storage_backend": "local | s3_compatible",
  "file_size_bytes": 10485760,
  "file_size_mb": 10.0,
  "created_by_username": "string | null",
  "created_at": "ISO8601"
}
```

`storage_key` はレスポンスに含めない（内部実装の詳細）。

---

## バックアップエンドポイント

### POST /api/v2/organizations/{org_id}/servers/{server_id}/backups — バックアップ作成

**認証:** `backup.create` 権限

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字、禁止文字: `/ \ : * ? " < > \|` | ○ |
| description | string | 最大 500 文字 | - |

**レスポンス (202):**
```json
{
  "backup": { ...BackupResponse (status=creating) },
  "job": { ...JobResponse (type=backup_create) }
}
```

**ジョブ内処理:**
1. Runner にサーバーディレクトリの tar.gz 圧縮を依頼
2. 生成されたアーカイブをストレージバックエンドに転送
3. `file_size_bytes`、`storage_key` を更新、`status=completed`
4. 失敗時: `status=failed`

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/backups/upload — バックアップアップロード

外部で作成したバックアップを取り込む。

**Note:** バックアップ作成 (POST .../backups) は非同期ジョブだが、アップロードは **同期処理 (201)** とする。理由: クライアントはアップロード完了まで接続を保持するため、非同期化しても体験上の差がなく、ジョブへの移行によるオーバーヘッドが不要のため。2GB のファイルをストリーミング転送するため、クライアント側のタイムアウト設定に注意する。

**認証:** `backup.create` 権限

**リクエスト (multipart/form-data):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| file | UploadFile | `.tar.gz` / `.tgz` のみ | ○ |
| name | string | 1-100 文字 | - (デフォルト: ファイル名から生成) |
| description | string | 最大 500 文字 | - |

**制約:** ファイルサイズ上限 2GB（ストリーミング転送、メモリに全展開しない）

**レスポンス (201):** `BackupResponse (status=completed)`

**処理フロー:**
1. ファイル形式確認 (tar.gz / tgz)
2. アーカイブ安全性検証（パストラバーサル・シンボリックリンク確認）
3. ストレージバックエンドにストリーミング転送
4. `status=completed` でレコード作成

**エラー:**
- 400 `Invalid file format`
- 413 `File exceeds size limit`
- 422 `Archive contains unsafe paths`

---

### GET /api/v2/organizations/{org_id}/servers/{server_id}/backups — サーバーのバックアップ一覧

**認証:** `backup.read` 権限

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| backup_type | enum | フィルタ |
| status | enum | フィルタ |
| page | int | デフォルト 1 |
| page_size | int (1-100) | デフォルト 50 |

**レスポンス (200):**
```json
{
  "backups": [ ...BackupResponse[] ],
  "total_count": 25,
  "total_size_bytes": 1073741824,
  "page": 1,
  "page_size": 50
}
```

---

### GET /api/v2/organizations/{org_id}/backups — Organization 全バックアップ一覧

**認証:** `backup.read` 権限

**クエリパラメータ:** 上記と同じ + `server_id` (フィルタ)

**レスポンス (200):** 上記と同じ形式

---

### GET /api/v2/organizations/{org_id}/backups/{backup_id} — バックアップ詳細

**認証:** `backup.read` 権限

**レスポンス (200):** `BackupResponse`

**エラー:**
- 404 `Backup not found`

---

### DELETE /api/v2/organizations/{org_id}/backups/{backup_id} — バックアップ削除

**認証:** `backup.delete` 権限

**レスポンス (200):**
```json
{ "message": "Backup deleted successfully" }
```

**処理フロー:**
1. ストレージバックエンドからファイルを削除
2. DB レコードを削除（論理削除なし、物理削除）
3. 監査ログ記録

---

### GET /api/v2/organizations/{org_id}/backups/{backup_id}/download — バックアップダウンロード

**認証:** `backup.read` 権限

**前提条件:** `status=completed`

**レスポンス (200):** バイナリストリーム (`application/gzip`)

**ファイル名形式:** `{server_slug}_{backup_name}_{backup_id_prefix}.tar.gz`

**処理フロー:**
- `local` バックエンド: ファイルを直接ストリーミング
- `s3_compatible` バックエンド: 署名付き URL を生成してリダイレクト (302) または直接プロキシ

**エラー:**
- 400 `Backup is not completed`
- 404 `Backup file not found in storage`

---

### POST /api/v2/organizations/{org_id}/backups/{backup_id}/restore — バックアップ復元

**認証:** `backup.restore` 権限

**前提条件:** `status=completed`

**リクエスト (JSON):**
| フィールド | 型 | 必須 | 説明 |
|-----------|-----|-----|------|
| target_server_id | UUID | - | 省略時は元サーバーに復元 |
| confirm | bool | ○ (true 必須) | 誤操作防止 |
| create_pre_restore_backup | bool | - (デフォルト true) | 復元前に現在の状態を自動バックアップ |

**レスポンス (202):**
```json
{
  "job": { ...JobResponse (type=backup_restore) },
  "pre_restore_backup": { ...BackupResponse | null }
}
```

**ジョブ内処理:**
1. 対象サーバーが `stopped` または `error` であることを確認
2. `create_pre_restore_backup=true` の場合、現在の状態を `pre_restore` タイプで自動バックアップ
3. サーバー `status=restoring` に更新
4. ストレージバックエンドからアーカイブを取得し Runner 経由でサーバーディレクトリに展開
5. 完了後: サーバー `status=stopped`
6. 失敗時: サーバー `status=error`

**クロス Organization の復元は不可**（target_server は同一 Organization 内のサーバーのみ）

**エラー:**
- 400 `confirm must be true`
- 400 `Backup is not completed`
- 409 `Target server must be stopped`
- 403 `Target server is in a different organization`

---

## バックアップスケジュールエンドポイント

> **Phase 2 機能。** 手動バックアップは MVP (Phase 1) で実装するが、スケジュール自動バックアップは Phase 2 での実装とする。

### POST /api/v2/organizations/{org_id}/servers/{server_id}/backup-schedule — スケジュール作成

**認証:** `backup.create` 権限

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| schedule_expression | string | 1-100 文字、形式は別途定義 | ○ |
| timezone | string | 有効な IANA タイムゾーン | - (デフォルト UTC) |
| max_backups | int | 1-100 | ○ |
| enabled | bool | - | - (デフォルト true) |
| only_when_running | bool | - | - (デフォルト true) |

**レスポンス (201):** `BackupScheduleResponse`
```json
{
  "id": "uuid",
  "server_id": "uuid",
  "schedule_expression": "string",
  "timezone": "Asia/Tokyo",
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
1. 同サーバーの既存スケジュールがあれば 409
2. `schedule_expression` を解析して `next_backup_at` を算出
3. スケジュールログ記録 (`action=created`)

**エラー:**
- 409 `Schedule already exists for this server`
- 422 `Invalid schedule_expression`

---

### GET /api/v2/organizations/{org_id}/servers/{server_id}/backup-schedule — スケジュール取得

**認証:** `backup.read` 権限

**レスポンス (200):** `BackupScheduleResponse`

**エラー:**
- 404 `No schedule found for this server`

---

### PUT /api/v2/organizations/{org_id}/servers/{server_id}/backup-schedule — スケジュール更新

**認証:** `backup.create` 権限

**リクエスト (JSON):** (すべて任意)
```json
{
  "schedule_expression": "string",
  "timezone": "Asia/Tokyo",
  "max_backups": 14,
  "enabled": false,
  "only_when_running": true
}
```

**処理フロー:**
1. `schedule_expression` が変更された場合は `next_backup_at` を再算出
2. スケジュールログ記録 (`action=updated`, `old_config` / `new_config` 付き)

**レスポンス (200):** `BackupScheduleResponse`

---

### DELETE /api/v2/organizations/{org_id}/servers/{server_id}/backup-schedule — スケジュール削除

**認証:** `backup.delete` 権限

**レスポンス (200):**
```json
{ "message": "Backup schedule deleted successfully" }
```

**処理フロー:**
1. スケジュールログ記録 (`action=deleted`)
2. DB レコードを削除

---

### GET /api/v2/organizations/{org_id}/servers/{server_id}/backup-schedule/logs — スケジュールログ一覧

**認証:** `backup.read` 権限

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| page | int | 1 |
| page_size | int (1-100) | 20 |

**レスポンス (200):**
```json
{
  "logs": [
    {
      "id": "uuid",
      "action": "created | updated | deleted | executed | skipped",
      "reason": "string | null",
      "old_config": null,
      "new_config": null,
      "executed_by_username": "string | null",
      "created_at": "ISO8601"
    }
  ],
  "total_count": 50
}
```

---

### GET /api/v2/organizations/{org_id}/backup-schedule/status — Organization 全スケジュール状態

**認証:** `backup.read` 権限

**レスポンス (200):**
```json
{
  "total_schedules": 5,
  "enabled_schedules": 4,
  "schedules": [
    {
      "server_id": "uuid",
      "server_name": "string",
      "enabled": true,
      "next_backup_at": "ISO8601",
      "last_backup_at": "ISO8601 | null"
    }
  ]
}
```

---

## スケジューラー動作仕様

- **チェック間隔:** 1 分ごと（スケジューラーが `next_backup_at <= now(UTC)` を確認）
- **実行条件:** `enabled=true` AND `next_backup_at <= now(UTC)`
- **only_when_running=true:** サーバーが `running` 状態でない場合はスキップ（`action=skipped` をログ記録）
- **実行後:** `last_backup_at` を更新し、`schedule_expression` から次回 `next_backup_at` を算出
- **max_backups 超過時:** 最も古い `scheduled` タイプのバックアップを自動削除（`manual` / `pre_restore` は削除しない）
- **実行はジョブキュー経由:** スケジューラーは `backup_create` ジョブをキューに追加するだけで、実際の処理はジョブワーカーが行う

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| バックアップ名 | 1-100 文字、禁止文字: `/ \ : * ? " < > \|` |
| 説明 | 最大 500 文字 |
| max_backups | 1-100 |
| timezone | 有効な IANA タイムゾーン識別子 |
| schedule_expression | 1-100 文字、アプリケーションが解析可能な形式 |
| アップロードサイズ上限 | 2GB |

---

## 監査イベント一覧

| イベント | action 値 | resource_type |
|--------|-----------|---------------|
| バックアップ作成開始 | `backup_create` | backup |
| バックアップ削除 | `backup_delete` | backup |
| バックアップ復元開始 | `backup_restore` | backup |
| スケジュール作成 | `backup_schedule_create` | backup |
| スケジュール更新 | `backup_schedule_update` | backup |
| スケジュール削除 | `backup_schedule_delete` | backup |
