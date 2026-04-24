# 仕様書: 認証 / テナント / ユーザー管理

## 概要

v2 の認証・ユーザー管理は以下の原則で設計する:

- **User はグローバルな認証主体。** テナントに依存しない汎用アカウント
- **権限はテナント単位の Member レベルで機能別に付与。** User モデルにロール列は持たない
- **JWT の `sub` は `user_id`。** username 変更によるトークン再発行問題を排除する
- **リフレッシュトークンはデバイス/セッション単位で管理。** ログアウトは当該デバイスのみ失効
- **テナントへの参加は招待ベース。** 自己申請承認フローは持たない
- **論理削除を採用。** User/Tenant/Workspace/Member はすべて物理削除しない

---

## データモデル

### User

グローバルな認証アカウント。テナントやロールに依存しない。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| email | string(255) | UNIQUE, NOT NULL | - | ログイン識別子 |
| username | string(50) | UNIQUE, NOT NULL | - | 表示名 |
| hashed_password | string(255) | NOT NULL | - | bcrypt ハッシュ |
| is_active | bool | NOT NULL | true | false の場合すべての操作を拒否 |
| email_verified | bool | NOT NULL | false | メール確認済みフラグ (Phase 2) |
| deleted_at | datetime(tz) | - | NULL | 論理削除日時 (NULL = 有効) |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**ロールフィールドなし。** 権限は `Member` レコードで管理する。

---

### Tenant

課金・クォータ・メンバーシップの単位となる組織。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| name | string(100) | NOT NULL | - | テナント表示名 |
| slug | string(50) | UNIQUE, NOT NULL | - | URL に使用する識別子 (英数字/ハイフン) |
| owner_user_id | UUID | FK(users.id), NOT NULL | - | オーナーユーザー |
| deleted_at | datetime(tz) | - | NULL | 論理削除日時 |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

---

### Workspace

テナント内の論理グルーピング (例: `prod`, `dev`)。サーバー/グループ/テンプレートはいずれかの Workspace に属する。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| tenant_id | UUID | FK(tenants.id), NOT NULL | - | 所属テナント |
| name | string(100) | NOT NULL | - | Workspace 名 |
| description | text | - | NULL | 説明 |
| deleted_at | datetime(tz) | - | NULL | 論理削除日時 |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**UNIQUE 制約:** (tenant_id, name) — 同一テナント内で名前重複不可

---

### Member

User とテナントの紐付け。テナント内でのロールと個別権限を保持する。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| tenant_id | UUID | FK(tenants.id), NOT NULL | - | 所属テナント |
| user_id | UUID | FK(users.id), NOT NULL | - | ユーザー |
| role_template | enum | NOT NULL | viewer | owner / admin / operator / viewer |
| custom_permissions | JSON | - | {} | ロールテンプレートへの個別追加/取り消し |
| invited_by_user_id | UUID | FK(users.id), ON DELETE SET NULL | - | 招待者 |
| joined_at | datetime(tz) | NOT NULL | now() | - |
| deleted_at | datetime(tz) | - | NULL | 論理削除 (テナント脱退) |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**UNIQUE 制約:** (tenant_id, user_id)

**custom_permissions の構造:**
```json
{
  "grant": ["server.delete", "backup.restore"],
  "revoke": ["workspace.manage"]
}
```

---

### WorkspaceMember

Member と Workspace の紐付け。Workspace レベルでの追加制限を付与できる。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| workspace_id | UUID | FK(workspaces.id), NOT NULL | - | - |
| member_id | UUID | FK(members.id), NOT NULL | - | - |
| custom_permissions | JSON | - | {} | Workspace レベルの追加制限 |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**UNIQUE 制約:** (workspace_id, member_id)

---

### TenantInvitation (Phase 2)

テナントへの招待トークン管理。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| tenant_id | UUID | FK(tenants.id), NOT NULL | - | - |
| email | string(255) | NOT NULL | - | 招待先メールアドレス |
| role_template | enum | NOT NULL | viewer | 招待時に付与するロールテンプレート |
| token | string(64) | UNIQUE, NOT NULL | - | URL-safe ランダムトークン |
| invited_by_user_id | UUID | FK(users.id), NOT NULL | - | 招待者 |
| expires_at | datetime(tz) | NOT NULL | - | 有効期限 (デフォルト: 7日後) |
| accepted_at | datetime(tz) | - | NULL | 承諾日時 |
| declined_at | datetime(tz) | - | NULL | 拒否日時 |
| created_at | datetime(tz) | NOT NULL | now() | - |

**招待の有効条件:** `accepted_at IS NULL` AND `declined_at IS NULL` AND `expires_at > now()`

---

### PersonalAccessToken (Phase 2)

Member 権限のサブセットとして発行する API トークン。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| member_id | UUID | FK(members.id), NOT NULL | - | 発行対象メンバー |
| name | string(100) | NOT NULL | - | トークン名 (用途識別) |
| token_hash | string(64) | UNIQUE, NOT NULL | - | トークンの SHA256 ハッシュ |
| permissions | JSON | NOT NULL | [] | Member 権限のサブセット |
| last_used_at | datetime(tz) | - | NULL | 最終使用日時 |
| expires_at | datetime(tz) | - | NULL | 有効期限 (NULL = 無期限) |
| revoked_at | datetime(tz) | - | NULL | 失効日時 |
| created_at | datetime(tz) | NOT NULL | now() | - |

**Note:** トークン文字列は発行時の1回のみ返却。以降は hash のみ保存。

---

### RefreshToken

デバイス/セッション単位のリフレッシュトークン。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| token_hash | string(64) | UNIQUE, NOT NULL | - | トークンの SHA256 ハッシュ |
| user_id | UUID | FK(users.id), NOT NULL | - | - |
| device_name | string(200) | - | NULL | User-Agent などデバイス識別情報 |
| expires_at | datetime(tz) | NOT NULL | - | 有効期限 (デフォルト: 30日後) |
| last_used_at | datetime(tz) | - | NULL | 最終使用日時 |
| revoked_at | datetime(tz) | - | NULL | 失効日時 (NULL = 有効) |
| created_at | datetime(tz) | NOT NULL | now() | - |

**トークンの有効条件:** `revoked_at IS NULL` AND `expires_at > now()`

**ローテーション戦略:** 使用ごとに新しいリフレッシュトークンを発行し、旧トークンは失効させる (Refresh Token Rotation)。ただしグローバルな全失効はしない — 当該セッションのトークンのみを対象とする。

---

## 権限定義

### RoleTemplate 一覧

| ロール | 説明 |
|--------|------|
| `owner` | テナントオーナー。全権限。他の owner を指定可能 |
| `admin` | 全権限。ただし tenant.delete 不可 |
| `operator` | サーバー・バックアップ・ファイル・グループ・テンプレートの操作権限 |
| `viewer` | 全リソースの読み取り専用 |

### Permission 一覧

**テナントレベル:**

| permission | 説明 | owner | admin | operator | viewer |
|-----------|------|:-----:|:-----:|:--------:|:------:|
| `tenant.read` | テナント情報閲覧 | ✓ | ✓ | ✓ | ✓ |
| `tenant.settings.manage` | テナント設定変更 | ✓ | ✓ | - | - |
| `tenant.delete` | テナント削除 | ✓ | - | - | - |
| `tenant.members.read` | メンバー一覧閲覧 | ✓ | ✓ | ✓ | ✓ |
| `tenant.members.manage` | メンバー管理 (招待/ロール変更/削除) | ✓ | ✓ | - | - |
| `audit.read` | 監査ログ閲覧 | ✓ | ✓ | - | - |

**Workspace・リソースレベル:**

| permission | 説明 | owner | admin | operator | viewer |
|-----------|------|:-----:|:-----:|:--------:|:------:|
| `workspace.read` | Workspace 閲覧 | ✓ | ✓ | ✓ | ✓ |
| `workspace.manage` | Workspace 設定変更・メンバー管理 | ✓ | ✓ | - | - |
| `workspace.delete` | Workspace 削除 | ✓ | ✓ | - | - |
| `server.read` | サーバー情報閲覧 | ✓ | ✓ | ✓ | ✓ |
| `server.create` | サーバー作成 | ✓ | ✓ | ✓ | - |
| `server.delete` | サーバー削除 | ✓ | ✓ | ✓ | - |
| `server.start` | サーバー起動 | ✓ | ✓ | ✓ | - |
| `server.stop` | サーバー停止/再起動/強制停止 | ✓ | ✓ | ✓ | - |
| `server.command` | コンソールコマンド送信 | ✓ | ✓ | ✓ | - |
| `server.settings.manage` | サーバー設定変更 | ✓ | ✓ | ✓ | - |
| `backup.read` | バックアップ閲覧 | ✓ | ✓ | ✓ | ✓ |
| `backup.create` | バックアップ作成 | ✓ | ✓ | ✓ | - |
| `backup.delete` | バックアップ削除 | ✓ | ✓ | ✓ | - |
| `backup.restore` | バックアップ復元 | ✓ | ✓ | ✓ | - |
| `file.read` | ファイル閲覧・ダウンロード | ✓ | ✓ | ✓ | ✓ |
| `file.write` | ファイル書き込み・アップロード | ✓ | ✓ | ✓ | - |
| `file.delete` | ファイル削除 | ✓ | ✓ | ✓ | - |
| `group.read` | グループ閲覧 | ✓ | ✓ | ✓ | ✓ |
| `group.manage` | グループ作成・編集・削除・アタッチ | ✓ | ✓ | ✓ | - |
| `template.read` | テンプレート閲覧 | ✓ | ✓ | ✓ | ✓ |
| `template.manage` | テンプレート作成・編集・削除 | ✓ | ✓ | ✓ | - |

---

## JWT 仕様

```json
{
  "sub": "<user_id (UUID)>",
  "email": "user@example.com",
  "iat": 1700000000,
  "exp": 1700003600
}
```

- `sub` は `user_id` (不変の UUID)。username 変更に影響されない
- テナントコンテキストは JWT に含めない。リクエストのパスパラメータ (`tenant_id`) で解決する
- アクセストークン有効期限: **1時間**
- リフレッシュトークン有効期限: **30日**

---

## 認証エンドポイント

### POST /api/v2/auth/register — ユーザー登録

**認証:** 不要

**レート制限:** 5 リクエスト / 分 / IP

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| email | string | 有効なメール形式 | ○ |
| username | string | 英数字/アンダースコア、2-50 文字 | ○ |
| password | string | パスワードポリシー参照 | ○ |

**レスポンス (201):**
```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "username": "string",
    "created_at": "ISO8601"
  },
  "message": "Registration successful"
}
```

**処理フロー:**
1. email 重複チェック → 重複なら 409
2. username 重複チェック → 重複なら 409
3. パスワードポリシー検証
4. bcrypt でパスワードをハッシュ化して User 作成
5. (Phase 2) メール確認リンクを送信

**Note:** v1 の「最初の登録者を自動 admin」は廃止。v2 ではテナントを自分で作成して owner になる。

**エラー:**
- 409 `Email already registered`
- 409 `Username already taken`
- 422 パスワードポリシー違反

---

### POST /api/v2/auth/login — ログイン

**認証:** 不要

**レート制限:** 10 リクエスト / 分 / IP (失敗時はカウントを増加)

**リクエスト (JSON):**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| email | string | ○ |
| password | string | ○ |
| device_name | string | - (デフォルト: User-Agent から生成) |

**レスポンス (200):**
```json
{
  "access_token": "string (JWT)",
  "refresh_token": "string",
  "token_type": "bearer",
  "expires_in": 3600
}
```

**処理フロー:**
1. email でユーザーを検索
2. ユーザーが存在しないまたはパスワード不一致 → 401 + 監査ログ (失敗)
3. `deleted_at IS NOT NULL` → 401
4. `is_active == false` → 403
5. 新しいリフレッシュトークンを生成 (device_name を記録)
6. access_token (JWT) を生成して返却 + 監査ログ (成功)

**エラー:**
- 401 `Invalid email or password`
- 403 `Account is deactivated`
- 429 レート制限超過

---

### POST /api/v2/auth/refresh — トークン更新

**認証:** 不要

**レート制限:** 20 リクエスト / 分 / ユーザー

**リクエスト (JSON):**
```json
{ "refresh_token": "string" }
```

**レスポンス (200):** ログインと同じ `TokenResponse`

**処理フロー:**
1. refresh_token の SHA256 ハッシュで DB を検索
2. 見つからない → 401
3. `revoked_at IS NOT NULL` または `expires_at <= now()` → 401 + 監査ログ (失敗)
4. 対応 User を取得。`is_active == false` または `deleted_at IS NOT NULL` → 401
5. 旧リフレッシュトークンを失効させ、新しいリフレッシュトークンを発行 (Rotation)
6. 新しい access_token を生成して返却 + last_used_at を更新 + 監査ログ (成功)

**エラー:**
- 401 `Invalid or expired refresh token`

---

### POST /api/v2/auth/logout — ログアウト (現在のデバイス)

**認証:** 不要 (refresh_token を受け取って処理)

**リクエスト (JSON):**
```json
{ "refresh_token": "string" }
```

**レスポンス (200):**
```json
{ "message": "Logged out successfully" }
```

**処理フロー:**
1. refresh_token の hash で DB を検索し、`revoked_at = now()` に更新
2. 見つからない場合もエラーを返さず 200 を返す (冪等)
3. 監査ログ記録

---

### POST /api/v2/auth/logout/all — 全デバイスログアウト

**認証:** User (access_token)

**レスポンス (200):**
```json
{ "message": "Logged out from all devices", "revoked_count": 3 }
```

**処理フロー:**
1. 対象ユーザーの有効なリフレッシュトークンをすべて失効 (`revoked_at = now()`)
2. 監査ログ記録

---

## 自分自身のエンドポイント

### GET /api/v2/users/me — 自分のプロフィール取得

**認証:** User (JWT)

**レスポンス (200):**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "username": "string",
  "is_active": true,
  "email_verified": false,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

**エラー:**
- 401 トークン無効

---

### PUT /api/v2/users/me — プロフィール更新

**認証:** User (JWT)

**リクエスト (JSON):** (すべて任意)
| フィールド | 型 | 制約 |
|-----------|-----|------|
| username | string | 英数字/アンダースコア、2-50 文字 |
| email | string | 有効なメール形式 |

**レスポンス (200):**
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "username": "string",
  "updated_at": "ISO8601"
}
```

**処理フロー:**
1. username が変更される場合、重複チェック (自分自身を除く) → 重複なら 409
2. email が変更される場合、重複チェック (自分自身を除く) → 重複なら 409
3. 変更を保存
4. **access_token の再発行なし** (JWT の sub は user_id なので username 変更の影響を受けない)

**エラー:**
- 409 `Username already taken`
- 409 `Email already registered`

---

### PUT /api/v2/users/me/password — パスワード変更

**認証:** User (JWT)

**リクエスト (JSON):**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| current_password | string | ○ |
| new_password | string | ○ |

**レスポンス (200):**
```json
{ "message": "Password changed successfully" }
```

**処理フロー:**
1. current_password を bcrypt で検証 → 不一致なら 400
2. new_password がパスワードポリシーを満たすか確認
3. new_password をハッシュ化して保存
4. 現在のセッション以外のリフレッシュトークンをすべて失効させる (セキュリティ強制ログアウト)
5. 監査ログ記録

**Note:** パスワード変更後は他のデバイスが強制ログアウトされる。現在のデバイスは継続利用可能。

**エラー:**
- 400 `Current password is incorrect`
- 422 新パスワードポリシー違反

---

### DELETE /api/v2/users/me — 自分のアカウント削除

**認証:** User (JWT)

**リクエスト (JSON):**
```json
{ "password": "string" }
```

**レスポンス (200):**
```json
{ "message": "Account deleted successfully" }
```

**処理フロー:**
1. パスワード検証 → 不一致なら 400
2. 自分が `owner` である Tenant が存在する場合は削除不可 (先に owner を移譲または Tenant を削除する必要がある)
3. `deleted_at = now()` で論理削除 (物理削除しない)
4. 全リフレッシュトークンを失効
5. 監査ログ記録

**エラー:**
- 400 `Password is incorrect`
- 409 `You are the owner of one or more tenants. Transfer ownership or delete them first.`

---

### GET /api/v2/users/me/sessions — セッション一覧

**認証:** User (JWT)

**レスポンス (200):**
```json
{
  "sessions": [
    {
      "id": "uuid",
      "device_name": "Chrome on Windows",
      "created_at": "ISO8601",
      "last_used_at": "ISO8601",
      "expires_at": "ISO8601",
      "is_current": true
    }
  ]
}
```

---

### DELETE /api/v2/users/me/sessions/{session_id} — 特定セッション失効

**認証:** User (JWT)

**レスポンス (200):**
```json
{ "message": "Session revoked successfully" }
```

**処理フロー:**
1. 対象セッションが自分のものであることを確認
2. `revoked_at = now()` に更新

---

### GET /api/v2/users/me/tenants — 所属テナント一覧

**認証:** User (JWT)

**レスポンス (200):**
```json
{
  "tenants": [
    {
      "id": "uuid",
      "name": "My Organization",
      "slug": "my-org",
      "role_template": "owner",
      "joined_at": "ISO8601"
    }
  ]
}
```

---

### GET /api/v2/users/me/tokens — PAT 一覧 (Phase 2)

**認証:** User (JWT)

**レスポンス (200):**
```json
{
  "tokens": [
    {
      "id": "uuid",
      "name": "CI/CD Token",
      "permissions": ["server.read", "backup.create"],
      "last_used_at": "ISO8601",
      "expires_at": null,
      "created_at": "ISO8601"
    }
  ]
}
```

---

### POST /api/v2/users/me/tokens — PAT 作成 (Phase 2)

**認証:** User (JWT)

**レート制限:** 10 リクエスト / 分 / ユーザー

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字 | ○ |
| tenant_id | UUID | - | ○ |
| permissions | string[] | Member 権限のサブセット | ○ |
| expires_at | datetime | NULL = 無期限 | - |

**レスポンス (201):**
```json
{
  "id": "uuid",
  "name": "CI/CD Token",
  "token": "pat_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "permissions": ["server.read", "backup.create"],
  "expires_at": null,
  "created_at": "ISO8601"
}
```

**Note:** `token` フィールドは作成時の1回のみ返却。以降は参照不可。

**バリデーション:**
- `permissions` は対象テナントにおける自分の Member 権限のサブセットでなければならない

**エラー:**
- 400 `Requested permissions exceed your member permissions`
- 404 テナントが存在しない / 自分が Member でない

---

### DELETE /api/v2/users/me/tokens/{token_id} — PAT 削除 (Phase 2)

**認証:** User (JWT)

**レスポンス (200):**
```json
{ "message": "Token revoked successfully" }
```

---

## テナント管理エンドポイント

### POST /api/v2/tenants — テナント作成

**認証:** User (JWT)

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字 | ○ |
| slug | string | 英数字/ハイフン、2-50 文字、システム内一意 | ○ |

**レスポンス (201):**
```json
{
  "id": "uuid",
  "name": "My Organization",
  "slug": "my-org",
  "owner_user_id": "uuid",
  "created_at": "ISO8601"
}
```

**処理フロー:**
1. slug の一意性を確認 → 重複なら 409
2. Tenant を作成
3. 作成者を `role_template=owner` の Member として登録
4. デフォルト Workspace (`default`) を作成
5. 監査ログ記録

**エラー:**
- 409 `Slug already taken`

---

### GET /api/v2/tenants/{tenant_id} — テナント詳細

**認証:** User (JWT) + テナントの Member であること

**レスポンス (200):**
```json
{
  "id": "uuid",
  "name": "My Organization",
  "slug": "my-org",
  "owner_user_id": "uuid",
  "member_count": 5,
  "workspace_count": 3,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

**エラー:**
- 403 テナントのメンバーでない
- 404 テナントが存在しない

---

### PUT /api/v2/tenants/{tenant_id} — テナント設定更新

**認証:** `tenant.settings.manage` 権限

**リクエスト (JSON):** (すべて任意)
| フィールド | 型 | 制約 |
|-----------|-----|------|
| name | string | 1-100 文字 |

**レスポンス (200):** `TenantResponse`

**エラー:**
- 403 権限不足

---

### DELETE /api/v2/tenants/{tenant_id} — テナント削除

**認証:** `tenant.delete` 権限 (owner のみ)

**リクエスト (JSON):**
```json
{ "confirm": true }
```

**レスポンス (200):**
```json
{ "message": "Tenant deleted successfully" }
```

**処理フロー:**
1. `confirm: true` であることを確認
2. Tenant を論理削除 (`deleted_at = now()`)
3. 配下の Workspace/Member を論理削除 (カスケード)
4. 監査ログ記録

**エラー:**
- 400 `confirm must be true`
- 403 owner 以外は削除不可

---

## メンバー管理エンドポイント

### GET /api/v2/tenants/{tenant_id}/members — メンバー一覧

**認証:** `tenant.members.read` 権限

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| role_template | enum | フィルタ |
| page | int | デフォルト 1 |
| page_size | int (1-100) | デフォルト 50 |

**レスポンス (200):**
```json
{
  "members": [
    {
      "user_id": "uuid",
      "username": "string",
      "email": "string",
      "role_template": "operator",
      "custom_permissions": { "grant": [], "revoke": [] },
      "joined_at": "ISO8601"
    }
  ],
  "total_count": 5,
  "page": 1,
  "page_size": 50
}
```

---

### GET /api/v2/tenants/{tenant_id}/members/{user_id} — メンバー詳細

**認証:** `tenant.members.read` 権限

**レスポンス (200):** `MemberDetailResponse` (上記の1件分)

---

### PUT /api/v2/tenants/{tenant_id}/members/{user_id} — メンバー権限変更

**認証:** `tenant.members.manage` 権限

**リクエスト (JSON):** (すべて任意)
```json
{
  "role_template": "operator",
  "custom_permissions": {
    "grant": ["server.delete"],
    "revoke": ["workspace.manage"]
  }
}
```

**レスポンス (200):** 更新後の `MemberDetailResponse`

**バリデーション:**
- 自分自身のロールを `owner` 以外に変更は不可
- `owner` ロールに変更できるのは既存の `owner` のみ
- `owner` が自分のロールを変更する場合は他に `owner` が必要

**エラー:**
- 400 `Cannot demote yourself as the only owner`
- 403 権限不足

---

### DELETE /api/v2/tenants/{tenant_id}/members/{user_id} — メンバー削除 (テナント脱退)

**認証:** `tenant.members.manage` 権限 (または自分自身の脱退)

**レスポンス (200):**
```json
{ "message": "Member removed successfully" }
```

**処理フロー:**
1. 論理削除 (`deleted_at = now()`)
2. `owner` が最後の1人なら削除不可
3. 配下の WorkspaceMember を削除
4. 監査ログ記録

**エラー:**
- 400 `Cannot remove the last owner`
- 403 権限不足

---

## 招待エンドポイント (Phase 2)

### POST /api/v2/tenants/{tenant_id}/invitations — 招待送信

**認証:** `tenant.members.manage` 権限

**リクエスト (JSON):**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| email | string | ○ |
| role_template | enum | ○ |

**レスポンス (201):**
```json
{
  "id": "uuid",
  "email": "invite@example.com",
  "role_template": "operator",
  "expires_at": "ISO8601",
  "created_at": "ISO8601"
}
```

**処理フロー:**
1. 対象メールが既にテナントのアクティブメンバーなら 409
2. 同一メールへの未承諾招待が存在する場合は上書き (再送)
3. TenantInvitation レコードを作成し、トークンを生成
4. (Phase 2) 招待メールを送信
5. 監査ログ記録

**エラー:**
- 409 `User is already a member of this tenant`

---

### GET /api/v2/tenants/{tenant_id}/invitations — 招待一覧

**認証:** `tenant.members.manage` 権限

**レスポンス (200):**
```json
{
  "invitations": [
    {
      "id": "uuid",
      "email": "invite@example.com",
      "role_template": "operator",
      "invited_by_username": "string",
      "expires_at": "ISO8601",
      "status": "pending"
    }
  ]
}
```

**status の値:** `pending` / `accepted` / `declined` / `expired`

---

### DELETE /api/v2/tenants/{tenant_id}/invitations/{invitation_id} — 招待取り消し

**認証:** `tenant.members.manage` 権限

**レスポンス (200):**
```json
{ "message": "Invitation cancelled" }
```

---

### POST /api/v2/invitations/{token}/accept — 招待承諾

**認証:** User (JWT)

**レスポンス (200):**
```json
{
  "message": "Invitation accepted",
  "tenant_id": "uuid",
  "tenant_name": "My Organization",
  "role_template": "operator"
}
```

**処理フロー:**
1. token でTenantInvitation を検索
2. 有効期限・承諾/拒否済みチェック
3. 招待メールアドレスと自分のメールアドレスが一致するか確認
4. Member レコードを作成 (`role_template` を設定)
5. `accepted_at = now()` を記録
6. 監査ログ記録

**エラー:**
- 404 招待が存在しない
- 410 招待期限切れ / 承諾/拒否済み
- 403 招待されたメールアドレスと異なるアカウント

---

### POST /api/v2/invitations/{token}/decline — 招待拒否

**認証:** User (JWT) または未認証 (メールリンクから)

**レスポンス (200):**
```json
{ "message": "Invitation declined" }
```

**処理フロー:**
1. token で TenantInvitation を検索 → 有効期限チェック
2. `declined_at = now()` を記録

---

## Workspace エンドポイント

### POST /api/v2/tenants/{tenant_id}/workspaces — Workspace 作成

**認証:** `workspace.manage` 権限

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字 | ○ |
| description | string | 最大 500 文字 | - |

**レスポンス (201):**
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "name": "production",
  "description": "string|null",
  "created_at": "ISO8601"
}
```

**エラー:**
- 409 同一テナント内で名前重複

---

### GET /api/v2/tenants/{tenant_id}/workspaces — Workspace 一覧

**認証:** `workspace.read` 権限

**レスポンス (200):**
```json
{
  "workspaces": [
    {
      "id": "uuid",
      "name": "production",
      "description": "string",
      "server_count": 3,
      "created_at": "ISO8601"
    }
  ]
}
```

---

### GET /api/v2/tenants/{tenant_id}/workspaces/{workspace_id} — Workspace 詳細

**認証:** `workspace.read` 権限

**レスポンス (200):** `WorkspaceDetailResponse`

---

### PUT /api/v2/tenants/{tenant_id}/workspaces/{workspace_id} — Workspace 更新

**認証:** `workspace.manage` 権限

**リクエスト (JSON):** (すべて任意)
```json
{
  "name": "string",
  "description": "string"
}
```

**レスポンス (200):** `WorkspaceDetailResponse`

---

### DELETE /api/v2/tenants/{tenant_id}/workspaces/{workspace_id} — Workspace 削除

**認証:** `workspace.delete` 権限

**レスポンス (200):**
```json
{ "message": "Workspace deleted successfully" }
```

**処理フロー:**
1. Workspace 内にサーバーが存在する場合は削除不可
2. 論理削除 (`deleted_at = now()`)
3. 配下の WorkspaceMember を削除
4. 監査ログ記録

**エラー:**
- 409 `Workspace has active servers. Delete or move them first.`

---

### GET /api/v2/tenants/{tenant_id}/workspaces/{workspace_id}/members — Workspace メンバー一覧

**認証:** `workspace.read` 権限

**レスポンス (200):**
```json
{
  "members": [
    {
      "user_id": "uuid",
      "username": "string",
      "tenant_role_template": "operator",
      "workspace_custom_permissions": {},
      "joined_at": "ISO8601"
    }
  ]
}
```

---

### POST /api/v2/tenants/{tenant_id}/workspaces/{workspace_id}/members — Workspace メンバー追加

**認証:** `workspace.manage` 権限

**リクエスト (JSON):**
```json
{
  "user_id": "uuid",
  "custom_permissions": {}
}
```

**前提条件:** 対象ユーザーがテナントのアクティブ Member であること

**レスポンス (201):** 追加された `WorkspaceMemberResponse`

**エラー:**
- 404 ユーザーがテナントメンバーでない
- 409 既に Workspace メンバー

---

### DELETE /api/v2/tenants/{tenant_id}/workspaces/{workspace_id}/members/{user_id} — Workspace メンバー削除

**認証:** `workspace.manage` 権限

**レスポンス (200):**
```json
{ "message": "Member removed from workspace" }
```

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| メールアドレス | RFC 5322 準拠の有効なメール形式、最大 255 文字 |
| username | 英数字/アンダースコアのみ、2-50 文字、システム内一意 |
| パスワード (最小) | 8 文字以上 |
| パスワード (最大) | 128 文字以下 |
| パスワード (複雑性) | 大文字・小文字・数字・記号のうち 2 種類以上を含む |
| テナント名 | 1-100 文字 |
| テナント slug | 英数字とハイフンのみ、2-50 文字、先頭/末尾はハイフン不可 |
| Workspace 名 | 1-100 文字 |
| PAT 名 | 1-100 文字 |
| role_template | owner / admin / operator / viewer のいずれか |

---

## 監査イベント一覧

| イベント | action 値 | resource_type |
|--------|-----------|---------------|
| ログイン成功 | `auth_login_success` | authentication |
| ログイン失敗 | `auth_login_failure` | authentication |
| トークン更新 | `auth_token_refresh` | authentication |
| ログアウト (単一) | `auth_logout` | authentication |
| ログアウト (全デバイス) | `auth_logout_all` | authentication |
| ユーザー登録 | `user_register` | user |
| プロフィール更新 | `user_profile_update` | user |
| パスワード変更 | `user_password_change` | user |
| アカウント削除 | `user_delete` | user |
| テナント作成 | `tenant_create` | tenant |
| テナント設定変更 | `tenant_update` | tenant |
| テナント削除 | `tenant_delete` | tenant |
| メンバー追加 | `member_add` | tenant |
| メンバー権限変更 | `member_role_change` | tenant |
| メンバー削除 | `member_remove` | tenant |
| 招待送信 | `invitation_send` | tenant |
| 招待承諾 | `invitation_accept` | tenant |
| 招待取り消し | `invitation_cancel` | tenant |
| Workspace 作成 | `workspace_create` | workspace |
| Workspace 削除 | `workspace_delete` | workspace |
| PAT 作成 | `pat_create` | user |
| PAT 削除 | `pat_revoke` | user |
