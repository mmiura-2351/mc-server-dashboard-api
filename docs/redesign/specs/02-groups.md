# 仕様書: グループ管理 (Groups)

グループは Minecraft の OP リストまたはホワイトリストをまとめた「プレイヤー集合」です。
グループをサーバーに attach することで、対応する JSON ファイル (ops.json / whitelist.json) が自動生成・更新されます。

## データモデル

### Group

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| name | string(100) | NOT NULL | - | グループ名 |
| description | text | - | NULL | 説明 |
| type | enum | NOT NULL | - | op / whitelist |
| players | JSON | NOT NULL | [] | プレイヤー配列 |
| owner_id | int | FK(users.id), NOT NULL | - | 所有者 |
| is_template | bool | NOT NULL | false | テンプレートフラグ |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**players の構造 (JSON 配列の各要素):**
```json
{
  "uuid": "string (最大36文字)",
  "username": "string (最大16文字)",
  "added_at": "ISO8601 タイムスタンプ"
}
```

**GroupType:**
- `op` — OP リスト
- `whitelist` — ホワイトリスト

### ServerGroup (グループ↔サーバー 関連)

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| server_id | int | FK(servers.id), NOT NULL | - | - |
| group_id | int | FK(groups.id), NOT NULL | - | - |
| priority | int | NOT NULL | 0 | 優先度 (0-100, 高いほど優先) |
| attached_at | datetime(tz) | NOT NULL | now() | attach 日時 |

**UNIQUE 制約:** (server_id, group_id)

---

## エンドポイント

### POST /api/v1/groups — グループ作成

**認証:** User

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字、英数字+スペース+ハイフン+アンダースコアのみ | ○ |
| group_type | enum | op / whitelist | ○ |
| description | string | 最大 500 文字 | - |

**レスポンス (201):** `GroupResponse`
```json
{
  "id": 1,
  "name": "string",
  "description": "string|null",
  "type": "op|whitelist",
  "players": [{ "uuid": "...", "username": "...", "added_at": "..." }],
  "owner_id": 1,
  "is_template": false,
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

**処理フロー:**
1. 同一オーナーの同名グループ存在チェック
2. Group レコード作成 (players=[])
3. 監査ログ記録

**エラー:**
- 400 `Group with this name already exists`
- 400 バリデーションエラー (名前の形式)

---

### GET /api/v1/groups — グループ一覧

**認証:** User

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| group_type | enum | op / whitelist でフィルタ (任意) |

**レスポンス (200):**
```json
{
  "groups": [ ...GroupResponse[] ],
  "total": 10
}
```

**注意:** v1 ではすべての認証済みユーザーが全グループを閲覧できる (Phase 1 の共有リソースモデル)。

---

### GET /api/v1/groups/{group_id} — グループ詳細

**認証:** User

**レスポンス (200):** `GroupResponse`

**エラー:**
- 404 `Group not found`

---

### PUT /api/v1/groups/{group_id} — グループ更新

**認証:** User

**リクエスト:**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| name | string | 任意 |
| description | string | 任意 |

**レスポンス (200):** `GroupResponse`

**処理フロー:**
1. name を変更する場合、同一オーナーの重複チェック
2. 変更を保存
3. 監査ログ (old_values / new_values 含む)

**エラー:**
- 404 `Group not found`
- 400 `Group with this name already exists`

---

### DELETE /api/v1/groups/{group_id} — グループ削除

**認証:** User

**レスポンス (204):** 空

**処理フロー:**
1. サーバーへの attach が存在する場合は削除不可
2. 監査ログ記録後に削除

**エラー:**
- 404 `Group not found`
- 400 `Cannot delete group that is attached to servers`

---

### POST /api/v1/groups/{group_id}/players — プレイヤー追加

**認証:** User

**リクエスト:**
| フィールド | 型 | 説明 |
|-----------|-----|------|
| uuid | string | プレイヤー UUID (36 文字以内) |
| username | string | プレイヤー名 (1-16 文字、英数字+アンダースコア) |
| player_name | string | username の別名 |

uuid または username/player_name のいずれかが必要。

**UUID フォーマット:** `^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$`

**処理フロー:**
1. uuid のみの場合 → Mojang API で username を解決 (失敗時は `uuid[:8]` をフォールバック)
2. username のみの場合 → Mojang API で UUID を解決 (失敗時はオフライン UUID を生成)
3. 同 UUID が既存の場合 → username を更新 (重複追加なし)
4. Group の players に追加してコミット
5. 影響するすべてのサーバーのファイルを更新 (リトライ付き、最大 3 回)
6. 稼働中サーバーにリアルタイムコマンドを送信 (ベストエフォート)
7. 監査ログ記録

**エラー:**
- 404 `Group not found`
- 400 uuid/username いずれも未指定

---

### DELETE /api/v1/groups/{group_id}/players/{uuid} — プレイヤー削除

**認証:** User

**レスポンス (200):** `GroupResponse`

**処理フロー:**
1. uuid で players を検索
2. 見つからない → 404
3. players から削除してコミット
4. 影響サーバーのファイル更新 (リトライ付き)
5. 稼働中サーバーにリアルタイム deop/whitelist remove コマンド送信
6. 監査ログ記録

**エラー:**
- 404 `Group not found`
- 404 `Player not found in group`

---

### POST /api/v1/groups/{group_id}/servers — サーバーに attach

**認証:** ServerOwner または Admin

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| server_id | int | >= 1 | ○ |
| priority | int | 0-100 | 任意 (デフォルト 0) |

**レスポンス (200):**
```json
{ "message": "Group {group_id} attached to server {server_id}" }
```

**処理フロー:**
1. server_id の Server を取得 (404 なら失敗)
2. 権限チェック: `user.role == admin OR server.owner_id == user.id`
3. 既に attach 済みなら 400
4. ServerGroup レコード作成
5. サーバーファイル更新 (リトライ付き)
6. 監査ログ記録

**エラー:**
- 404 `Server not found` / `Group not found`
- 403 `Only server owners and admins can attach groups to servers`
- 400 `Group is already attached to this server`

---

### DELETE /api/v1/groups/{group_id}/servers/{server_id} — サーバーから detach

**認証:** ServerOwner または Admin

**レスポンス (200):**
```json
{ "message": "Group {group_id} detached from server {server_id}" }
```

**処理フロー:**
1. 権限チェック (attach と同じ)
2. ServerGroup レコードを削除
3. サーバーファイル更新
4. op グループの場合 → deop コマンドを稼働中サーバーに送信

**エラー:**
- 404 Server / Group / 関連付けが見つからない
- 403 権限なし

---

### GET /api/v1/groups/{group_id}/servers — グループが attach されているサーバー一覧

**認証:** User

**レスポンス (200):**
```json
{
  "group_id": 1,
  "servers": [
    {
      "id": 1,
      "name": "string",
      "status": "stopped|starting|running|stopping|error",
      "priority": 0,
      "attached_at": "ISO8601"
    }
  ]
}
```

---

### GET /api/v1/groups/servers/{server_id} — サーバーの attach グループ一覧

**認証:** User

**レスポンス (200):**
```json
{
  "server_id": 1,
  "groups": [
    {
      "id": 1,
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

**注意:** priority 降順、次いで Group.name 昇順でソート。

---

## サーバーファイル同期ロジック

グループの内容変更 (プレイヤー追加/削除、attach/detach) が発生した場合、以下を実行する:

1. サーバーに attach されているすべてのグループを priority 降順で取得
2. op グループのプレイヤーを収集 → `ops.json` を生成
   - 形式: `[{"uuid": "...", "name": "...", "level": 4, "bypassesPlayerLimit": true}]`
3. whitelist グループのプレイヤーを収集 → `whitelist.json` を生成
   - 形式: `[{"uuid": "...", "name": "..."}]`
4. 同じ UUID は priority が高いグループのみ採用 (重複排除)
5. サーバーが稼働中の場合:
   - whitelist グループがある → `whitelist reload` コマンドを送信
   - op グループがある → ops.json を再送信

**ファイル更新のリトライ:** 最大 3 回、1秒 / 2秒 / 3秒 の指数バックオフ。
失敗してもプレイヤー追加/削除のロールバックはしない (ベストエフォート)。

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| グループ名 | 1-100 文字、英数字・スペース・ハイフン・アンダースコアのみ、空白のみ不可 |
| 説明 | 最大 500 文字 |
| プレイヤー UUID | 32-36 文字、UUID 形式 |
| プレイヤー名 | 1-16 文字、英数字+アンダースコア (`^[a-zA-Z0-9_]{1,16}$`) |
| priority | 0-100 の整数 |

## 監査イベント一覧

| イベント | アクション名 |
|---------|------------|
| グループ作成 | `group_created` |
| グループ更新 | `group_updated` |
| グループ削除 | `group_deleted` |
| プレイヤー追加 | `player_added_to_group` |
| プレイヤー削除 | `player_removed_from_group` |
| サーバーに attach | `group_attached_to_server` |
| サーバーから detach | `group_detached_from_server` |
