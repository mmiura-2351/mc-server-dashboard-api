# 仕様書: 監査ログ

## 設計方針

- **Organization スコープ。** 監査ログはすべて `organization_id` を持ち、Organization のオーナー・管理者が閲覧できる。認証操作など組織横断イベントは `organization_id = NULL` で記録する
- **不変ログ。** 監査ログは更新・削除しない。クエリ API のみ提供する
- **ミドルウェア自動記録。** 各ルート処理の後処理として監査ミドルウェアが自動的に DB へ書き込む。重要操作は即時書き込み、その他は非同期バッファ書き込みとする
- **センシティブデータ除外。** `details` フィールドからパスワード・トークン等を自動マスクする

---

## データモデル

### AuditLog

| フィールド | 型 | 制約 | 説明 |
|-----------|-----|------|------|
| id | UUID | PK | - |
| organization_id | UUID | FK(organizations.id), ON DELETE SET NULL, NULL許可 | 対象 Organization (認証操作等は NULL) |
| user_id | UUID | FK(users.id), ON DELETE SET NULL, NULL許可 | 実行ユーザー (未認証の場合 NULL) |
| action | string(100) | NOT NULL | 操作種別 (下記一覧参照) |
| resource_type | string(50) | NOT NULL | 対象リソース種別 |
| resource_id | UUID | NULL許可 | 対象リソース ID |
| details | JSON | NULL許可 | 操作の詳細情報 (センシティブ除外済み) |
| ip_address | string(45) | NULL許可 | クライアント IP (IPv6 対応) |
| created_at | datetime(tz) | NOT NULL | - |

---

## アクション一覧

各仕様書の「監査イベント一覧」を集約したもの。詳細は各仕様書を参照。

| カテゴリ | action 値 | resource_type |
|---------|-----------|---------------|
| **認証** | `auth_login_success` | authentication |
| | `auth_login_failure` | authentication |
| | `auth_token_refresh` | authentication |
| | `auth_logout` | authentication |
| | `auth_logout_all` | authentication |
| | `auth_token_revoked` | authentication |
| **ユーザー** | `user_register` | user |
| | `user_update` | user |
| | `user_password_change` | user |
| | `user_delete` | user |
| | `pat_create` | user |
| | `pat_revoke` | user |
| **Organization** | `org_create` | organization |
| | `org_update` | organization |
| | `org_delete` | organization |
| | `org_transfer_ownership` | organization |
| | `member_invite` | organization |
| | `member_join` | organization |
| | `member_permissions_update` | organization |
| | `member_remove` | organization |
| | `invitation_cancel` | organization |
| **サーバー** | `server_create` | server |
| | `server_delete` | server |
| | `server_start` | server |
| | `server_stop` | server |
| | `server_force_stop` | server |
| | `server_restart` | server |
| | `server_update` | server |
| | `server_settings_update` | server |
| | `server_command` | server |
| **バックアップ** | `backup_create` | backup |
| | `backup_upload` | backup |
| | `backup_delete` | backup |
| | `backup_restore` | backup |
| | `backup_schedule_create` | backup |
| | `backup_schedule_update` | backup |
| | `backup_schedule_delete` | backup |
| **グループ** | `group_create` | group |
| | `group_update` | group |
| | `group_delete` | group |
| | `player_add` | group |
| | `player_remove` | group |
| | `group_attach` | group |
| | `group_detach` | group |
| **ファイル** | `file_write` | file |
| | `file_delete` | file |
| | `file_rename` | file |
| | `file_upload` | file |
| | `file_version_restore` | file |
| | `file_version_delete` | file |

---

## エンドポイント

### GET /api/v2/organizations/{org_id}/audit/logs — Organization 監査ログ一覧

**必要権限:** `audit.read` 権限 (デフォルトでは owner / admin ロールのみ付与。`custom_permissions` で operator に grant することも可能)

**クエリパラメータ:**
| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|---------|------|
| page | int | 1 | - |
| page_size | int (1-100) | 50 | - |
| user_id | UUID | - | 特定ユーザーでフィルタ |
| action | string | - | 部分一致フィルタ |
| resource_type | string | - | フィルタ |
| resource_id | UUID | - | フィルタ |
| from | datetime | - | 開始日時 (ISO8601) |
| to | datetime | - | 終了日時 (ISO8601) |

**レスポンス (200):**
```json
{
  "logs": [
    {
      "id": "uuid",
      "organization_id": "uuid",
      "user_id": "uuid | null",
      "username": "string | null",
      "action": "server_start",
      "resource_type": "server",
      "resource_id": "uuid | null",
      "details": {},
      "ip_address": "192.168.1.1",
      "created_at": "ISO8601"
    }
  ],
  "total_count": 200,
  "page": 1,
  "page_size": 50
}
```

---

### GET /api/v2/organizations/{org_id}/audit/stats — Organization 監査統計

**必要権限:** `audit.read` 権限

**レスポンス (200):**
```json
{
  "organization_id": "uuid",
  "total_logs": 10000,
  "recent_logs_24h": 150,
  "most_active_users_30d": [
    { "user_id": "uuid", "username": "string", "activity_count": 500 }
  ],
  "most_common_actions_30d": [
    { "action": "server_start", "count": 200 }
  ],
  "resource_type_distribution_30d": [
    { "resource_type": "server", "count": 300 }
  ],
  "generated_at": "ISO8601"
}
```

---

### GET /api/v2/users/me/audit-logs — 自分のアクティビティ

**必要権限:** 認証済みユーザー

自分が実行した操作のログを全 Organization 横断で取得する。

**クエリパラメータ:**
| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|---------|------|
| page | int | 1 | - |
| page_size | int (1-100) | 50 | - |
| action | string | - | 部分一致フィルタ |
| from | datetime | - | 開始日時 |
| to | datetime | - | 終了日時 |

**レスポンス (200):**
```json
{
  "logs": [
    {
      "id": "uuid",
      "organization_id": "uuid | null",
      "action": "server_start",
      "resource_type": "server",
      "resource_id": "uuid | null",
      "details": {},
      "ip_address": "192.168.1.1",
      "created_at": "ISO8601"
    }
  ],
  "total_count": 80,
  "page": 1,
  "page_size": 50
}
```

---

## 監査ミドルウェア

すべての変更系 API エンドポイントのレスポンス完了後に、監査情報を自動的に DB へ記録する。

**リクエスト毎の処理:**
1. `X-Forwarded-For` → `X-Real-IP` → `request.client.host` の順でクライアント IP を抽出
2. JWT からユーザー ID と Organization ID を抽出 (未認証の場合は NULL)
3. レスポンスコードが 4xx/5xx の場合も `auth_login_failure` など対応するアクションで記録
4. 通常操作: 非同期バッファに蓄積してバッチ書き込み
5. 重要操作 (下記): 即時同期書き込み

**即時書き込み対象:**
`server_delete`, `backup_restore`, `backup_delete`, `member_remove`, `org_delete`, `server_command`, `file_delete`, `auth_token_revoked`

**センシティブデータフィルタリング:**

`details` フィールドに含まれる以下のキーワードを持つ値は記録前に `"[REDACTED]"` へ置き換える:

`password`, `token`, `secret`, `key`, `auth`, `credential`, `private`, `jwt`, `refresh`

文字列値は 1000 文字を超える場合は切り詰める。

---

## 保持ポリシー

監査ログの保持期間は環境変数 `AUDIT_LOG_RETENTION_DAYS` で設定する (デフォルト: 365 日)。

バックグラウンドのスケジューラーが毎日 1 回、保持期間を超えたレコードを削除する。

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| page_size | 1-100 |
| from / to | ISO8601 形式 |
| from と to の関係 | `from <= to` |
