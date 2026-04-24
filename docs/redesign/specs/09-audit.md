# 仕様書: 監査ログ / 可視性制御

## データモデル

### AuditLog

| フィールド | 型 | 制約 | 説明 |
|-----------|-----|------|------|
| id | int | PK | - |
| user_id | int | FK(users.id) | 実行ユーザー (未認証の場合 NULL) |
| action | string(100) | NOT NULL | 操作種別 (下記一覧参照) |
| resource_type | string(50) | NOT NULL | 対象リソース種別 |
| resource_id | int | - | 対象リソース ID |
| details | JSON | - | 操作の詳細情報 |
| ip_address | string(45) | - | クライアント IP (IPv6 対応) |
| created_at | datetime(tz) | NOT NULL | - |

**アクション一覧:**
| カテゴリ | action 値 |
|---------|-----------|
| 認証 | auth_login_success, auth_login_failure, auth_token_refresh, auth_logout |
| ユーザー管理 | user_approve, user_role_change, user_delete |
| サーバー | server_create, server_delete, server_start, server_stop, server_command |
| バックアップ | backup_create, backup_delete, backup_restore |
| グループ | group_create, group_delete, group_updated, player_added_to_group, player_removed_from_group, group_attached_to_server, group_detached_from_server |
| テンプレート | template_create, template_delete |
| ファイル | file_write, file_delete, file_rename |
| 権限 | permission_check_granted, permission_check_denied |
| セキュリティ | security_* (severity 付き) |
| 管理操作 | admin_* |

**resource_type 一覧:** authentication, user, server, backup, file, group, template, permission, security, admin_action

### ResourceVisibility (Phase 2 機能)

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| resource_type | enum | NOT NULL | - | server / group |
| resource_id | int | NOT NULL | - | - |
| visibility_type | enum | NOT NULL | private | private / specific_users / role_based / public |
| role_restriction | enum | - | NULL | user / operator / admin (role_based のみ使用) |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**UNIQUE 制約:** (resource_type, resource_id)

**VisibilityType:**
- `public` — すべての認証済みユーザーが閲覧可能 (v1 の動作と同等)
- `private` — 所有者と admin のみ閲覧可能
- `role_based` — 指定ロール以上のユーザーが閲覧可能
- `specific_users` — 個別に許可したユーザーのみ閲覧可能

### ResourceUserAccess (Phase 2 機能)

| フィールド | 型 | 制約 | 説明 |
|-----------|-----|------|------|
| id | int | PK | - |
| resource_visibility_id | int | FK(resource_visibility.id), ON DELETE CASCADE, NOT NULL | - |
| user_id | int | FK(users.id), ON DELETE CASCADE, NOT NULL | - |
| granted_by_user_id | int | FK(users.id), ON DELETE SET NULL | - |
| created_at | datetime(tz) | NOT NULL | - |

**UNIQUE 制約:** (resource_visibility_id, user_id)

---

## 監査ログエンドポイント

### GET /api/v1/audit/logs — 監査ログ一覧

**認証:** User

**アクセス制御:**
- Admin: 任意の user_id でフィルタ可能
- 非 Admin: 自分のログのみ閲覧可能 (自動的に user_id を自分に固定)

**クエリパラメータ:**
| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|---------|------|
| page | int | 1 | - |
| page_size | int (1-100) | 50 | - |
| user_id | int | - | フィルタ (admin のみ任意指定) |
| action | string | - | 部分一致フィルタ |
| resource_type | string | - | フィルタ |
| resource_id | int | - | フィルタ |

**レスポンス (200):**
```json
{
  "logs": [
    {
      "id": 1,
      "user_id": 1,
      "action": "server_start",
      "resource_type": "server",
      "resource_id": 5,
      "details": {},
      "ip_address": "192.168.1.1",
      "created_at": "ISO8601",
      "user_email": "user@example.com"
    }
  ],
  "total_count": 200,
  "page": 1,
  "page_size": 50
}
```

---

### GET /api/v1/audit/security-alerts — セキュリティアラート (Admin)

**認証:** Admin

**クエリパラメータ:**
| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|---------|------|
| severity | string | - | low / medium / high / critical |
| limit | int (1-100) | 50 | - |

**レスポンス (200):** `List[AuditLogResponse]`

**フィルタ条件:** `resource_type = "security"`

---

### GET /api/v1/audit/user/{user_id}/activity — ユーザーアクティビティ

**認証:** User

**アクセス制御:**
- Admin: 任意の user_id 指定可能
- 非 Admin: 自分の user_id のみ

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| limit | int (1-200) | 100 |

**レスポンス (200):** `List[AuditLogResponse]`

**エラー:**
- 403 Non-admin accessing other user's activity
- 404 User not found

---

### GET /api/v1/audit/statistics — 監査統計 (Admin)

**認証:** Admin

**レスポンス (200):**
```json
{
  "total_audit_logs": 10000,
  "recent_logs_24h": 150,
  "security_events_7d": 5,
  "most_active_users_30d": [
    { "user_id": 1, "activity_count": 500 }
  ],
  "most_common_actions_30d": [
    { "action": "server_start", "count": 200 }
  ],
  "resource_type_distribution_30d": [
    { "resource_type": "server", "count": 300 }
  ],
  "statistics_generated_at": "ISO8601"
}
```

---

## 可視性制御エンドポイント (Phase 2)

### GET /visibility/{resource_type}/{resource_id} — 可視性設定取得

**認証:** Owner または Admin

**パスパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| resource_type | enum | server / group |
| resource_id | int | リソース ID |

**レスポンス (200):**
```json
{
  "resource_type": "server",
  "resource_id": 1,
  "visibility_type": "public",
  "role_restriction": null,
  "granted_users": null,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

---

### PUT /visibility/{resource_type}/{resource_id} — 可視性設定更新

**認証:** Owner または Admin

**リクエスト:**
```json
{
  "visibility_type": "role_based",
  "role_restriction": "operator"
}
```

**バリデーション:**
- `visibility_type=role_based` の場合 `role_restriction` は必須
- `visibility_type!=role_based` の場合 `role_restriction` は不可

**レスポンス (200):** `VisibilityInfoResponse`

---

### POST /visibility/{resource_type}/{resource_id}/grant-access — ユーザーアクセス付与

**認証:** Owner または Admin

**制約:** `visibility_type=specific_users` である必要がある

**リクエスト:**
```json
{ "user_id": 5 }
```

**レスポンス (200):**
```json
{
  "success": true,
  "message": "string",
  "user_id": 5,
  "granted_by_user_id": 1
}
```

---

### DELETE /visibility/{resource_type}/{resource_id}/revoke-access/{user_id} — アクセス取り消し

**認証:** Owner または Admin

**レスポンス (200):**
```json
{
  "success": true,
  "message": "string",
  "user_id": 5
}
```

---

### GET /visibility/migration/status — 移行状況確認 (Admin)

**認証:** Admin

**レスポンス (200):**
```json
{
  "migration_complete": false,
  "issues": ["Server ID 3 has no visibility config"],
  "resource_stats": {
    "servers": { "total": 10, "with_visibility": 8, "missing": 2 }
  },
  "visibility_distribution": {
    "server": { "public": 6, "private": 2 }
  }
}
```

---

### POST /visibility/migration/execute — 移行実行 (Admin)

**認証:** Admin

**処理:** 可視性設定が未作成のリソースに対して `visibility_type=public` で作成 (v1 の動作を維持)

**レスポンス (200):**
```json
{
  "success": true,
  "message": "string",
  "migration_counts": {
    "servers": 2,
    "groups": 0,
    "total": 2
  }
}
```

---

## 監査ミドルウェア

すべての変更系 API リクエストに自動的に監査情報を付与する。

**リクエスト毎の処理:**
1. ユニークな request_id を生成
2. クライアント IP を抽出 (`X-Forwarded-For`, `X-Real-IP`, `client.host` の順)
3. JWT からユーザー ID を抽出
4. リクエスト処理中に発生した監査イベントをバッファに蓄積
5. レスポンス完了後にバッファを DB に保存

**クリティカルアクション (即時保存):** user_delete, server_delete, backup_delete, role_change, user_approve, server_command, file_delete, admin_action

**センシティブデータフィルタリング:**
details フィールドから以下のキーワードを含むフィールドを自動的に除外 / マスク:
password, token, secret, key, auth, credential, private, sensitive, confidential, jwt, refresh

**文字列の切り詰め:** 1000 文字を超える値は切り詰める

## アクセス制御ロジック (可視性)

```
check_resource_access(user, resource_type, resource_id):
  1. user.role == admin → true (常にアクセス可)
  2. user.id == resource.owner_id → true (所有者は常にアクセス可)
  3. ResourceVisibility を取得
  4. visibility_type に応じて判定:
     - public → true
     - private → false
     - role_based → ロール階層 (user=1, operator=2, admin=3) でチェック
     - specific_users → ResourceUserAccess にエントリがあれば true
```
