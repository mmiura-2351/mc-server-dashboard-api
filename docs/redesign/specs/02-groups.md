# 仕様書: プレイヤーグループ管理 (Groups)

グループは Minecraft の OP リストまたはホワイトリストをまとめた「Minecraft プレイヤーの集合」です。
**ダッシュボードのユーザーとは無関係** — Minecraft プレイヤーを管理するため、ダッシュボードアカウントを持たないプレイヤーも追加できます。

グループは **Organization に所属** し、同じ Organization 内のサーバーにのみ attach できます。
グループをサーバーに attach することで、対応する JSON ファイル (`ops.json` / `whitelist.json`) が自動生成・更新されます。

---

## データモデル

### Group

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| organization_id | UUID | FK(organizations.id), NOT NULL | - | 所属 Organization |
| name | string(100) | NOT NULL | - | グループ名 |
| description | text | - | NULL | 説明 |
| type | enum | NOT NULL | - | op / whitelist |
| is_template | bool | NOT NULL | false | テンプレートフラグ (複製元として使いやすくする用途) |
| deleted_at | datetime(tz) | - | NULL | 論理削除日時 |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**UNIQUE 制約:** (organization_id, name) — 同一 Organization 内で名前重複不可

**GroupType:**
- `op` — OP リスト (`ops.json`)
- `whitelist` — ホワイトリスト (`whitelist.json`)

---

### GroupPlayer

グループに所属する Minecraft プレイヤー。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| group_id | UUID | FK(groups.id), NOT NULL | - | - |
| minecraft_uuid | string(36) | NOT NULL | - | Minecraft プレイヤー UUID |
| username | string(16) | NOT NULL | - | Minecraft プレイヤー名 |
| added_at | datetime(tz) | NOT NULL | now() | - |

**UNIQUE 制約:** (group_id, minecraft_uuid)

**Note:** v1 では players を Group の JSON 列に格納していたが、v2 では正規化して別テーブルに分離する。

---

### ServerGroup (グループ ↔ サーバー 関連)

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| server_id | UUID | FK(servers.id), NOT NULL | - | - |
| group_id | UUID | FK(groups.id), NOT NULL | - | - |
| priority | int | NOT NULL | 0 | 優先度 (0-100, 高いほど優先) |
| attached_at | datetime(tz) | NOT NULL | now() | attach 日時 |

**UNIQUE 制約:** (server_id, group_id)

**制約:** server と group は同一 Organization に属していなければならない

---

## エンドポイント

すべてのエンドポイントは Organization のメンバーシップを前提とする。
アクセス制御は `01-auth-users.md` で定義した permission に従う。

### POST /api/v2/organizations/{org_id}/groups — グループ作成

**認証:** `group.manage` 権限

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字、英数字・スペース・ハイフン・アンダースコアのみ | ○ |
| type | enum | op / whitelist | ○ |
| description | string | 最大 500 文字 | - |
| is_template | bool | - | - (デフォルト false) |

**レスポンス (201):** `GroupResponse`
```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "name": "string",
  "description": "string|null",
  "type": "op|whitelist",
  "is_template": false,
  "player_count": 0,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

**処理フロー:**
1. 同一 Organization 内の同名グループ存在チェック → 重複なら 409
2. Group レコード作成
3. 監査ログ記録

**エラー:**
- 409 `Group with this name already exists in the organization`
- 422 バリデーションエラー

---

### GET /api/v2/organizations/{org_id}/groups — グループ一覧

**認証:** `group.read` 権限

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| type | enum | op / whitelist でフィルタ |
| is_template | bool | テンプレートのみ / 通常のみでフィルタ |
| page | int | デフォルト 1 |
| page_size | int (1-100) | デフォルト 50 |

**レスポンス (200):**
```json
{
  "groups": [ ...GroupResponse[] ],
  "total_count": 10,
  "page": 1,
  "page_size": 50
}
```

---

### GET /api/v2/organizations/{org_id}/groups/{group_id} — グループ詳細

**認証:** `group.read` 権限

**レスポンス (200):**
```json
{
  "id": "uuid",
  "organization_id": "uuid",
  "name": "string",
  "description": "string|null",
  "type": "op|whitelist",
  "is_template": false,
  "players": [
    { "id": "uuid", "minecraft_uuid": "string", "username": "string", "added_at": "ISO8601" }
  ],
  "attached_server_count": 2,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

**エラー:**
- 404 `Group not found`

---

### PUT /api/v2/organizations/{org_id}/groups/{group_id} — グループ更新

**認証:** `group.manage` 権限

**リクエスト (JSON):** (すべて任意)
```json
{
  "name": "string",
  "description": "string",
  "is_template": true
}
```

**Note:** `type` (op/whitelist) は変更不可。変更が必要な場合は削除して再作成する。

**レスポンス (200):** `GroupResponse`

**処理フロー:**
1. name を変更する場合、同一 Organization 内の重複チェック
2. 変更を保存
3. 監査ログ記録

**エラー:**
- 404 `Group not found`
- 409 `Group with this name already exists in the organization`

---

### DELETE /api/v2/organizations/{org_id}/groups/{group_id} — グループ削除

**認証:** `group.manage` 権限

**レスポンス (200):**
```json
{ "message": "Group deleted successfully" }
```

**処理フロー:**
1. サーバーへの attach が存在する場合は削除不可
2. 論理削除 (`deleted_at = now()`)
3. 監査ログ記録

**エラー:**
- 404 `Group not found`
- 409 `Cannot delete group that is attached to servers`

---

## プレイヤー管理エンドポイント

### POST /api/v2/organizations/{org_id}/groups/{group_id}/players — プレイヤー追加

**認証:** `group.manage` 権限

**リクエスト (JSON):**
| フィールド | 型 | 説明 |
|-----------|-----|------|
| minecraft_uuid | string | プレイヤー UUID (任意) |
| username | string | プレイヤー名 (任意) |

`minecraft_uuid` または `username` のいずれかが必要。

**レスポンス (200):** 更新後の `GroupResponse`

**処理フロー:**
1. `minecraft_uuid` のみの場合 → Mojang API で username を解決 (失敗時は UUID 先頭8文字をフォールバック)
2. `username` のみの場合 → Mojang API で UUID を解決 (失敗時はオフライン UUID を生成)
3. 同 UUID が既存の場合 → username を更新 (重複追加なし)
4. GroupPlayer レコードを作成/更新
5. attach されているすべてのサーバーのファイルを更新 (リトライ付き、最大 3 回)
6. 稼働中サーバーへのリアルタイムコマンド送信 (ベストエフォート)
7. 監査ログ記録

**エラー:**
- 400 `Either minecraft_uuid or username is required`
- 404 `Group not found`

---

### DELETE /api/v2/organizations/{org_id}/groups/{group_id}/players/{minecraft_uuid} — プレイヤー削除

**認証:** `group.manage` 権限

**レスポンス (200):** 更新後の `GroupResponse`

**処理フロー:**
1. `minecraft_uuid` で GroupPlayer を検索 → 見つからなければ 404
2. GroupPlayer レコードを削除
3. attach されているすべてのサーバーのファイルを更新 (リトライ付き)
4. 稼働中サーバーへ deop / whitelist remove コマンドを送信 (ベストエフォート)
5. 監査ログ記録

**エラー:**
- 404 `Group not found`
- 404 `Player not found in group`

---

## サーバー attach / detach エンドポイント

### POST /api/v2/organizations/{org_id}/groups/{group_id}/servers — サーバーに attach

**認証:** `group.manage` 権限

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| server_id | UUID | - | ○ |
| priority | int | 0-100 | - (デフォルト 0) |

**レスポンス (200):**
```json
{ "message": "Group attached to server successfully" }
```

**処理フロー:**
1. server_id の Server を取得。存在しない / 同一 Organization でない → 404
2. 既に attach 済みなら 409
3. ServerGroup レコード作成
4. サーバーファイル更新 (リトライ付き)
5. 監査ログ記録

**エラー:**
- 404 `Server not found`
- 409 `Group is already attached to this server`

---

### DELETE /api/v2/organizations/{org_id}/groups/{group_id}/servers/{server_id} — サーバーから detach

**認証:** `group.manage` 権限

**レスポンス (200):**
```json
{ "message": "Group detached from server successfully" }
```

**処理フロー:**
1. ServerGroup レコードを削除
2. サーバーファイル更新 (リトライ付き)
3. op グループの場合 → 稼働中サーバーへ deop コマンドを送信
4. 監査ログ記録

**エラー:**
- 404 Server / Group / 関連付けが見つからない

---

### GET /api/v2/organizations/{org_id}/groups/{group_id}/servers — グループが attach されているサーバー一覧

**認証:** `group.read` 権限

**レスポンス (200):**
```json
{
  "group_id": "uuid",
  "servers": [
    {
      "id": "uuid",
      "name": "string",
      "status": "stopped|starting|running|stopping|error",
      "priority": 0,
      "attached_at": "ISO8601"
    }
  ]
}
```

---

### GET /api/v2/organizations/{org_id}/servers/{server_id}/groups — サーバーの attach グループ一覧

**認証:** `group.read` 権限

**レスポンス (200):**
```json
{
  "server_id": "uuid",
  "groups": [
    {
      "id": "uuid",
      "name": "string",
      "description": "string|null",
      "type": "op|whitelist",
      "priority": 0,
      "attached_at": "ISO8601",
      "player_count": 5
    }
  ]
}
```

**ソート:** priority 降順、次いで name 昇順

---

## サーバーファイル同期ロジック

グループの内容変更 (プレイヤー追加/削除、attach/detach) が発生した場合:

1. サーバーに attach されているすべてのグループを priority 降順で取得
2. op グループのプレイヤーを収集 → `ops.json` を生成
   ```json
   [{"uuid": "...", "name": "...", "level": 4, "bypassesPlayerLimit": true}]
   ```
3. whitelist グループのプレイヤーを収集 → `whitelist.json` を生成
   ```json
   [{"uuid": "...", "name": "..."}]
   ```
4. 同じ UUID は priority が高いグループのみ採用 (重複排除)
5. サーバーが稼働中の場合:
   - whitelist グループがある → `whitelist reload` コマンドを送信
   - op グループがある → `ops.json` 再送信後にリロード

**リトライ:** 最大 3 回、指数バックオフ (1秒 / 2秒 / 4秒)。
ファイル更新失敗時もプレイヤー操作のロールバックはしない (ベストエフォート)。

---

## Mojang API / UUID キャッシュ

プレイヤー UUID と username の解決は Mojang API への問い合わせを伴うため、中央でキャッシュする。

**キャッシュ仕様:**
- UUID → username: TTL 24 時間
- username → UUID: TTL 1 時間 (username 変更に追従するため短め)
- キャッシュストア: Redis または DB テーブル

**フォールバック:**
- UUID のみ指定でユーザー名解決失敗 → UUID 先頭 8 文字を username として使用
- username のみ指定で UUID 解決失敗 → オフライン UUID (SHA256 ベース) を生成

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| グループ名 | 1-100 文字、英数字・スペース・ハイフン・アンダースコアのみ、空白のみ不可 |
| 説明 | 最大 500 文字 |
| プレイヤー UUID | 32-36 文字、UUID 形式 |
| プレイヤー名 | 1-16 文字、英数字+アンダースコア (`^[a-zA-Z0-9_]{1,16}$`) |
| priority | 0-100 の整数 |

---

## 監査イベント一覧

| イベント | action 値 | resource_type |
|---------|-----------|---------------|
| グループ作成 | `group_create` | group |
| グループ更新 | `group_update` | group |
| グループ削除 | `group_delete` | group |
| プレイヤー追加 | `player_added_to_group` | group |
| プレイヤー削除 | `player_removed_from_group` | group |
| サーバーに attach | `group_attached_to_server` | group |
| サーバーから detach | `group_detached_from_server` | group |
