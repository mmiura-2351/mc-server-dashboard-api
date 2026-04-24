# 仕様書: 認証 / ユーザー管理

## データモデル

### User

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK, auto-increment | - | - |
| username | string(50) | UNIQUE, NOT NULL | - | 英数字のみ |
| email | string(255) | UNIQUE, NOT NULL | - | 有効なメール形式 |
| hashed_password | string(255) | NOT NULL | - | bcrypt ハッシュ |
| role | enum | NOT NULL | user | admin / operator / user |
| is_active | bool | NOT NULL | true | アカウント有効フラグ |
| is_approved | bool | NOT NULL | false | 管理者承認フラグ |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | 更新時自動更新 |

**ロール定義:**
- `user` — 一般ユーザー
- `operator` — オペレーター権限
- `admin` — 全権限

### RefreshToken

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| token | text | UNIQUE, NOT NULL | - | URL-safe ランダム文字列 (32 bytes) |
| user_id | int | FK(users.id), NOT NULL | - | - |
| expires_at | datetime(tz) | NOT NULL | - | 有効期限 |
| created_at | datetime(tz) | NOT NULL | now() | - |
| is_revoked | bool | NOT NULL | false | 失効フラグ |

**トークンの有効条件:** `is_revoked == false` AND `expires_at > now()`

---

## 認証エンドポイント

### POST /api/v1/auth/token — ログイン

**認証:** 不要

**リクエスト (form-data / OAuth2PasswordRequestForm):**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| username | string | ○ |
| password | string | ○ |

**レスポンス (200):**
```json
{
  "access_token": "string (JWT)",
  "refresh_token": "string",
  "token_type": "bearer"
}
```

**処理フロー:**
1. username でユーザーを検索
2. 見つからない / パスワード不一致 → 401 + 監査ログ (失敗)
3. `is_approved == false` → 403
4. 成功 → access_token (JWT, sub=username) + refresh_token を生成して返却 + 監査ログ (成功)

**エラー:**
- 401 `Incorrect username or password`
- 403 `Account pending approval`

---

### POST /api/v1/auth/refresh — トークン更新

**認証:** 不要

**リクエスト (JSON):**
```json
{ "refresh_token": "string" }
```

**レスポンス (200):** ログインと同じ `TokenResponse`

**処理フロー:**
1. refresh_token を検証 (存在・有効期限・is_revoked)
2. 無効 → 401 + 監査ログ (失敗)
3. 対応 User を取得。存在しない / `is_active == false` → 401
4. 新しい access_token + refresh_token を生成 (旧 refresh_token は失効) + 監査ログ (成功)

**重要:** refresh_token を新規発行する際、同一ユーザーの既存有効 refresh_token はすべて失効させる。

**エラー:**
- 401 `Invalid or expired refresh token`
- 401 `User not found or inactive`

---

### POST /api/v1/auth/logout — ログアウト

**認証:** 不要

**リクエスト (JSON):**
```json
{ "refresh_token": "string" }
```

**レスポンス (200):**
```json
{ "message": "Successfully logged out" }
```

**処理フロー:**
1. refresh_token を失効 (`is_revoked = true`)
2. 失効失敗 (トークン不在等) → 400
3. 成功 + 監査ログ

**エラー:**
- 400 `Invalid refresh token`

---

## ユーザー管理エンドポイント

### POST /api/v1/users/register — ユーザー登録

**認証:** 不要

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| username | string | UNIQUE | ○ |
| email | email | UNIQUE | ○ |
| password | string | - | ○ |

**レスポンス (201):** `UserResponse`

**処理フロー:**
1. username 重複チェック → 重複なら 400
2. ユーザー数が 0 の場合 (最初の登録) → `role=admin, is_approved=true`
3. それ以外 → `role=user, is_approved=false`
4. パスワードを bcrypt でハッシュ化して保存

**ビジネスルール:**
- 最初に登録したユーザーは自動的に admin 且つ承認済みになる

**エラー:**
- 400 `Username already registered`

---

### GET /api/v1/users/me — 自分のプロフィール取得

**認証:** User (JWT)

**レスポンス (200):** `UserResponse`
```json
{
  "id": 1,
  "username": "string",
  "email": "string",
  "is_active": true,
  "is_approved": true,
  "role": "user|operator|admin"
}
```

**エラー:**
- 401 トークン無効
- 400 `is_active == false`

---

### PUT /api/v1/users/me — プロフィール更新

**認証:** User (JWT)

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| username | string | - | 任意 |
| email | email | - | 任意 |

**レスポンス (200):**
```json
{
  "user": { ...UserResponse },
  "access_token": "string (username変更時のみ新トークン、それ以外は空文字列)",
  "token_type": "bearer"
}
```

**処理フロー:**
1. username が変更される場合、重複チェック (自分自身を除く)
2. email が変更される場合、重複チェック (自分自身を除く)
3. 変更を保存
4. username が変わった場合 → 新 access_token を生成 (JWT の sub が username のため)

**注意:** username を変えると JWT の `sub` が変わるため、新トークンを発行して返却する。フロントエンドは空文字列の場合はトークン更新しない。

**エラー:**
- 400 `Username already exists`
- 400 `Email already exists`

---

### PUT /api/v1/users/me/password — パスワード変更

**認証:** User (JWT)

**リクエスト (JSON):**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| current_password | string | ○ |
| new_password | string | ○ |

**レスポンス (200):** `UserWithToken` (新 access_token 付き)

**処理フロー:**
1. current_password を bcrypt で検証
2. 不一致 → 400
3. new_password をハッシュ化して保存
4. 新 access_token を発行して返却

**エラー:**
- 400 `Current password is incorrect`

---

### DELETE /api/v1/users/me — 自分のアカウント削除

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
1. パスワード検証
2. admin の場合、admin ユーザー数が 1 以下なら削除不可
3. DB からレコード削除

**エラー:**
- 400 `Password is incorrect`
- 400 `Cannot delete the last admin user`

---

### GET /api/v1/users/ — 全ユーザー一覧 (Admin only)

**認証:** Admin

**レスポンス (200):** `List[UserResponse]`

**エラー:**
- 403 Not admin

---

### POST /api/v1/users/approve/{user_id} — ユーザー承認 (Admin only)

**認証:** Admin

**レスポンス (200):** `UserResponse` (is_approved=true)

**処理フロー:**
1. 対象ユーザーを取得
2. `is_approved = true` に更新

**エラー:**
- 403 Not admin
- 404 User not found

---

### PUT /api/v1/users/role/{user_id} — ロール変更 (Admin only)

**認証:** Admin

**リクエスト (JSON):**
```json
{ "role": "admin|operator|user" }
```

**レスポンス (200):** `UserResponse`

**エラー:**
- 403 Not admin
- 404 User not found

---

### DELETE /api/v1/users/{user_id} — ユーザー削除 (Admin only)

**認証:** Admin

**レスポンス (200):**
```json
{ "message": "User deleted successfully" }
```

**処理フロー:**
1. 自分自身への削除は不可
2. 対象ユーザーが admin かつ admin が 1 人以下なら削除不可
3. DB から削除

**エラー:**
- 403 Not admin
- 404 User not found
- 400 `Cannot delete your own account`
- 400 `Cannot delete the last admin user`

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| username | 英数字のみ、最大 50 文字、システム内一意 |
| email | 有効なメール形式、システム内一意 |
| password | 最小要件なし (v1 実装では未定義のため v2 で設計要) |
| role | admin / operator / user のいずれか |

## 監査イベント一覧

| イベント | アクション名 | 条件 |
|--------|------------|------|
| ログイン成功 | `auth_login_success` | - |
| ログイン失敗 | `auth_login_failure` | reason: invalid_credentials |
| トークン更新成功 | `auth_token_refresh` | - |
| ログアウト | `auth_logout` | - |
| ユーザー承認 | `user_approve` | - |
| ロール変更 | `user_role_change` | - |
| ユーザー削除 | `user_delete` | - |
