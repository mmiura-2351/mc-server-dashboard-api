# 仕様書: 認証 / Organization / ユーザー管理

## 概要

v2 の認証・ユーザー管理は以下の原則で設計する:

- **User はグローバルな認証主体。** Organization に依存しない汎用アカウント
- **リソース分離の単位は Organization（1層）。** Tenant + Workspace の2層構造は採用しない
- **権限は Organization 単位の Member レベルで機能別に付与。** User モデルにロール列は持たない
- **JWT の `sub` は `user_id`。** username 変更によるトークン再発行問題を排除する
- **リフレッシュトークンはデバイス/セッション単位で管理。** ログアウトは当該デバイスのみ失効
- **Organization への参加は招待ベース。** 自己申請承認フローは持たない
- **論理削除を採用。** User / Organization / OrganizationMember はすべて物理削除しない

---

## データモデル

### User

グローバルな認証アカウント。Organization やロールに依存しない。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| email | string(255) | UNIQUE, NOT NULL | - | ログイン識別子 |
| username | string(50) | UNIQUE, NOT NULL | - | 表示名 |
| hashed_password | string(255) | NOT NULL | - | bcrypt ハッシュ |
| is_active | bool | NOT NULL | true | false の場合すべての操作を拒否 |
| deleted_at | datetime(tz) | - | NULL | 論理削除日時 (NULL = 有効) |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**ロールフィールドなし。** 権限は `OrganizationMember` レコードで管理する。

---

### Organization

リソース分離の単位。サーバー・バックアップ・グループ・テンプレートはいずれかの Organization に属する。ユーザーは複数の Organization に所属できる。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| name | string(100) | NOT NULL | - | 表示名 |
| slug | string(50) | UNIQUE, NOT NULL | - | URL に使用する識別子 (英数字/ハイフン) |
| owner_user_id | UUID | FK(users.id), NOT NULL | - | オーナーユーザー |
| deleted_at | datetime(tz) | - | NULL | 論理削除日時 |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

---

### OrganizationMember

User と Organization の紐付け。Organization 内でのロールと個別権限を保持する。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| organization_id | UUID | FK(organizations.id), NOT NULL | - | - |
| user_id | UUID | FK(users.id), NOT NULL | - | - |
| role_template | enum | NOT NULL | viewer | owner / admin / operator / viewer |
| custom_permissions | JSON | - | {} | ロールテンプレートへの個別追加/取り消し |
| invited_by_user_id | UUID | FK(users.id), ON DELETE SET NULL | - | 招待者 |
| joined_at | datetime(tz) | NOT NULL | now() | - |
| deleted_at | datetime(tz) | - | NULL | 論理削除 (Organization 脱退) |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**UNIQUE 制約:** (organization_id, user_id)

**custom_permissions の構造:**
```json
{
  "grant": ["server.delete", "backup.restore"],
  "revoke": ["file.delete"]
}
```

---

### OrganizationInvitation (Phase 2)

Organization への招待トークン管理。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| organization_id | UUID | FK(organizations.id), NOT NULL | - | - |
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

OrganizationMember 権限のサブセットとして発行する API トークン。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| member_id | UUID | FK(organization_members.id), NOT NULL | - | 発行対象メンバー |
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

**ローテーション戦略:** 使用ごとに新しいリフレッシュトークンを発行し、旧トークンを失効 (Refresh Token Rotation)。グローバルな全失効はしない — 当該セッションのみを対象とする。

---

## 権限定義

### RoleTemplate 一覧

| ロール | 説明 |
|--------|------|
| `owner` | Organization オーナー。全権限。他の owner を指定可能 |
| `admin` | 全権限。ただし `org.delete` 不可 |
| `operator` | サーバー・バックアップ・ファイル・グループ・テンプレートの操作権限 |
| `viewer` | 全リソースの読み取り専用 |

### Permission 一覧

| permission | 説明 | owner | admin | operator | viewer |
|-----------|------|:-----:|:-----:|:--------:|:------:|
| `org.read` | Organization 情報閲覧 | ✓ | ✓ | ✓ | ✓ |
| `org.settings.manage` | Organization 設定変更 | ✓ | ✓ | - | - |
| `org.delete` | Organization 削除 | ✓ | - | - | - |
| `org.members.read` | メンバー一覧閲覧 | ✓ | ✓ | ✓ | ✓ |
| `org.members.manage` | メンバー管理 (招待/ロール変更/削除) | ✓ | ✓ | - | - |
| `audit.read` | 監査ログ閲覧 | ✓ | ✓ | - | - |
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
- Organization コンテキストは JWT に含めない。リクエストのパスパラメータ (`organization_id`) で解決する
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

**Note:** 登録直後は Organization に所属しない。Organization を作成するか、招待を承諾することで使用を開始する。

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
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

---

### PUT /api/v2/users/me — プロフィール更新

**認証:** User (JWT)

**リクエスト (JSON):** (すべて任意)
| フィールド | 型 | 制約 |
|-----------|-----|------|
| username | string | 英数字/アンダースコア、2-50 文字 |
| email | string | 有効なメール形式 |

**レスポンス (200):** 更新後の `UserResponse`

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
4. 現在のセッション以外のリフレッシュトークンをすべて失効 (セキュリティ強制ログアウト)
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
2. 自分が `owner` である Organization が存在する場合は削除不可 (先に owner を移譲または Organization を削除する必要がある)
3. `deleted_at = now()` で論理削除
4. 全リフレッシュトークンを失効
5. 監査ログ記録

**エラー:**
- 400 `Password is incorrect`
- 409 `You are the owner of one or more organizations. Transfer ownership or delete them first.`

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

**エラー:**
- 404 セッションが存在しない / 自分のセッションでない

---

### GET /api/v2/users/me/organizations — 所属 Organization 一覧

**認証:** User (JWT)

**レスポンス (200):**
```json
{
  "organizations": [
    {
      "id": "uuid",
      "name": "身内グループA",
      "slug": "group-a",
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
      "organization_id": "uuid",
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
| organization_id | UUID | - | ○ |
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
- `permissions` は対象 Organization における自分の Member 権限のサブセットでなければならない

**エラー:**
- 400 `Requested permissions exceed your member permissions`
- 404 Organization が存在しない / 自分が Member でない

---

### DELETE /api/v2/users/me/tokens/{token_id} — PAT 削除 (Phase 2)

**認証:** User (JWT)

**レスポンス (200):**
```json
{ "message": "Token revoked successfully" }
```

---

## Organization エンドポイント

### POST /api/v2/organizations — Organization 作成

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
  "name": "身内グループA",
  "slug": "group-a",
  "owner_user_id": "uuid",
  "created_at": "ISO8601"
}
```

**処理フロー:**
1. slug の一意性を確認 → 重複なら 409
2. Organization を作成
3. 作成者を `role_template=owner` の OrganizationMember として登録
4. 監査ログ記録

**エラー:**
- 409 `Slug already taken`

---

### GET /api/v2/organizations/{org_id} — Organization 詳細

**認証:** User (JWT) + Organization の Member であること

**レスポンス (200):**
```json
{
  "id": "uuid",
  "name": "身内グループA",
  "slug": "group-a",
  "owner_user_id": "uuid",
  "member_count": 5,
  "server_count": 3,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

**エラー:**
- 403 Organization のメンバーでない
- 404 Organization が存在しない

---

### PUT /api/v2/organizations/{org_id} — Organization 設定更新

**認証:** `org.settings.manage` 権限

**リクエスト (JSON):** (すべて任意)
| フィールド | 型 | 制約 |
|-----------|-----|------|
| name | string | 1-100 文字 |

**レスポンス (200):** `OrganizationResponse`

**エラー:**
- 403 権限不足

---

### DELETE /api/v2/organizations/{org_id} — Organization 削除

**認証:** `org.delete` 権限 (owner のみ)

**リクエスト (JSON):**
```json
{ "confirm": true }
```

**レスポンス (200):**
```json
{ "message": "Organization deleted successfully" }
```

**処理フロー:**
1. `confirm: true` であることを確認
2. Organization 内にサーバーが存在する場合は削除不可
3. `deleted_at = now()` で論理削除 (カスケードで Member も論理削除)
4. 監査ログ記録

**エラー:**
- 400 `confirm must be true`
- 403 owner 以外は削除不可
- 409 `Organization has servers. Delete all servers first.` (論理削除されていないサーバーが1件以上ある場合。status に関わらず)

---

## メンバー管理エンドポイント

### GET /api/v2/organizations/{org_id}/members — メンバー一覧

**認証:** `org.members.read` 権限

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

### GET /api/v2/organizations/{org_id}/members/{user_id} — メンバー詳細

**認証:** `org.members.read` 権限

**レスポンス (200):** `MemberDetailResponse` (上記の1件分)

---

### PUT /api/v2/organizations/{org_id}/members/{user_id} — メンバー権限変更

**認証:** `org.members.manage` 権限

**リクエスト (JSON):** (すべて任意)
```json
{
  "role_template": "operator",
  "custom_permissions": {
    "grant": ["server.delete"],
    "revoke": ["file.delete"]
  }
}
```

**レスポンス (200):** 更新後の `MemberDetailResponse`

**バリデーション:**
- 自分自身のロールを `owner` 以外に変更は不可 (単独 owner の場合)
- `owner` ロールに変更できるのは既存の `owner` のみ

**エラー:**
- 400 `Cannot demote yourself as the only owner`
- 403 権限不足

---

### DELETE /api/v2/organizations/{org_id}/members/{user_id} — メンバー削除 / 脱退

**認証:** `org.members.manage` 権限 (または自分自身の脱退)

**レスポンス (200):**
```json
{ "message": "Member removed successfully" }
```

**処理フロー:**
1. `owner` が最後の1人なら削除不可
2. `deleted_at = now()` で論理削除
3. 監査ログ記録

**エラー:**
- 400 `Cannot remove the last owner`
- 403 権限不足

---

## 招待エンドポイント (Phase 2)

### POST /api/v2/organizations/{org_id}/invitations — 招待送信

**認証:** `org.members.manage` 権限

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
1. 対象メールが既にアクティブ Member なら 409
2. 同一メールへの未承諾招待が存在する場合は上書き (再送)
3. OrganizationInvitation レコードを作成
4. 監査ログ記録

**エラー:**
- 409 `User is already a member of this organization`

---

### GET /api/v2/organizations/{org_id}/invitations — 招待一覧

**認証:** `org.members.manage` 権限

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

### DELETE /api/v2/organizations/{org_id}/invitations/{invitation_id} — 招待取り消し

**認証:** `org.members.manage` 権限

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
  "organization_id": "uuid",
  "organization_name": "身内グループA",
  "role_template": "operator"
}
```

**処理フロー:**
1. token で OrganizationInvitation を検索
2. 有効期限・承諾/拒否済みチェック
3. 招待メールアドレスと自分のメールアドレスが一致するか確認
4. OrganizationMember レコードを作成 (`role_template` を設定)
5. `accepted_at = now()` を記録
6. 監査ログ記録

**エラー:**
- 404 招待が存在しない
- 410 招待期限切れ / 承諾/拒否済み
- 403 招待されたメールアドレスと異なるアカウント

---

### POST /api/v2/invitations/{token}/decline — 招待拒否

**認証:** User (JWT)

**レスポンス (200):**
```json
{ "message": "Invitation declined" }
```

**処理フロー:**
1. token で OrganizationInvitation を検索 → 有効期限チェック
2. `declined_at = now()` を記録

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| メールアドレス | RFC 5322 準拠の有効なメール形式、最大 255 文字 |
| username | 英数字/アンダースコアのみ、2-50 文字、システム内一意 |
| パスワード (最小) | 8 文字以上 |
| パスワード (最大) | 128 文字以下 |
| パスワード (複雑性) | 大文字・小文字・数字・記号のうち 2 種類以上を含む |
| Organization 名 | 1-100 文字 |
| Organization slug | 英数字とハイフンのみ、2-50 文字、先頭/末尾はハイフン不可 |
| PAT 名 | 1-100 文字 |
| role_template | owner / admin / operator / viewer のいずれか |

---

## 監査イベント一覧

| イベント | action 値 | resource_type |
|--------|-----------|---------------|
| ログイン成功 | `auth_login_success` | authentication |
| ログイン失敗 | `auth_login_failure` | authentication |
| トークン更新 | `auth_token_refresh` | authentication |
| ログアウト (単一デバイス) | `auth_logout` | authentication |
| ログアウト (全デバイス) | `auth_logout_all` | authentication |
| セッション失効 | `auth_token_revoked` | authentication |
| ユーザー登録 | `user_register` | user |
| プロフィール更新 | `user_update` | user |
| パスワード変更 | `user_password_change` | user |
| アカウント削除 | `user_delete` | user |
| Organization 作成 | `org_create` | organization |
| Organization 設定変更 | `org_update` | organization |
| Organization 削除 | `org_delete` | organization |
| 招待送信 | `member_invite` | organization |
| メンバー参加 (招待承諾) | `member_join` | organization |
| メンバー権限変更 | `member_role_change` | organization |
| メンバー削除 / 脱退 | `member_remove` | organization |
| 招待取り消し | `invitation_cancel` | organization |
| PAT 作成 | `pat_create` | user |
| PAT 失効 | `pat_revoke` | user |
