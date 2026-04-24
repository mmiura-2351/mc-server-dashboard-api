# 仕様書: テンプレート管理 (Templates)

サーバーの設定を再利用可能なテンプレートとして保存・共有する機能。

## データモデル

### Template

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| name | string(100) | NOT NULL | - | テンプレート名 |
| description | text | - | NULL | 説明 |
| minecraft_version | string(20) | NOT NULL | - | 例: "1.20.1" |
| server_type | enum | NOT NULL | - | vanilla / forge / paper 等 |
| configuration | JSON | NOT NULL | {} | server.properties 等の設定 |
| default_groups | JSON | - | NULL | デフォルトグループ設定 |
| created_by | int | FK(users.id), NOT NULL | - | 作成者 |
| is_public | bool | NOT NULL | false | 公開フラグ |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**configuration の構造:**
```json
{
  "server_properties": { "key": "value" },
  "files": ["eula.txt", "ops.json"],
  "directories": ["plugins", "mods", "config"],
  "metadata": { "source_server_id": 1 }
}
```

**default_groups の構造:**
```json
{
  "op_groups": [1, 2],
  "whitelist_groups": [3]
}
```

---

## エンドポイント

### POST /templates/from-server/{server_id} — サーバーからテンプレート作成

**認証:** Operator または Admin

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字 | ○ |
| description | string | 最大 500 文字 | - |
| is_public | bool | - | - (デフォルト false) |

**レスポンス (201):** `TemplateResponse`
```json
{
  "id": 1,
  "name": "string",
  "description": "string|null",
  "minecraft_version": "1.20.1",
  "server_type": "paper",
  "configuration": {},
  "default_groups": {"op_groups": [], "whitelist_groups": []},
  "created_by": 1,
  "is_public": false,
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "creator_name": "string"
}
```

**処理フロー:**
1. サーバーアクセス権確認
2. 権限確認 (operator または admin)
3. サーバーディレクトリから設定を抽出:
   - server.properties をパース
   - 重要ファイル一覧 (eula.txt, ops.json, whitelist.json 等)
   - 重要ディレクトリ一覧 (plugins, mods, config, datapacks)
4. Template レコード作成
5. テンプレートファイル (tar.gz) を生成 (重要ファイル/ディレクトリを含む)

**エラー:**
- 403 Not operator/admin
- 404 Server / directory not found
- 400 テンプレート作成エラー

---

### POST /templates/ — カスタムテンプレート作成

**認証:** Operator または Admin

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| name | string | 1-100 文字、形式チェックあり | ○ |
| description | string | 最大 500 文字 | - |
| minecraft_version | string | 形式: `\d+\.\d+(\.\d+)?` | ○ |
| server_type | enum | - | ○ |
| configuration | object | - | - (デフォルト {}) |
| default_groups | object | - | - |
| is_public | bool | - | - (デフォルト false) |

**レスポンス (201):** `TemplateResponse`

**エラー:**
- 403 Not operator/admin
- 400 バージョン形式不正

---

### GET /templates/ — テンプレート一覧

**認証:** User

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| minecraft_version | string | フィルタ |
| server_type | enum | フィルタ |
| is_public | bool | フィルタ |
| page | int | デフォルト 1 |
| size | int (1-100) | デフォルト 50 |

**アクセス制御:**
- Admin: 全テンプレートを閲覧可能
- それ以外: `is_public=true` または `created_by=自分のid` のもののみ

**レスポンス (200):**
```json
{
  "templates": [ ...TemplateResponse[] ],
  "total": 50,
  "page": 1,
  "size": 20
}
```

---

### GET /templates/{template_id} — テンプレート詳細

**認証:** User

**アクセス制御:** public / 自分が作成 / admin のいずれか

**レスポンス (200):** `TemplateResponse`

**エラー:**
- 403 Access denied
- 404 Not found

---

### PUT /templates/{template_id} — テンプレート更新

**認証:** Creator または Admin

**リクエスト (すべて任意):**
```json
{
  "name": "string",
  "description": "string",
  "configuration": {},
  "default_groups": {},
  "is_public": true
}
```

**レスポンス (200):** `TemplateResponse`

**エラー:**
- 403 Not creator/admin
- 400 バリデーションエラー

---

### DELETE /templates/{template_id} — テンプレート削除

**認証:** Creator または Admin

**レスポンス (204):** 空

**処理フロー:**
1. 使用中サーバー (template_id が設定されているサーバー) があれば削除不可
2. テンプレートファイル (tar.gz) を削除
3. DB レコードを削除

**エラー:**
- 403 Not creator/admin
- 404 Not found
- 409 Servers are using this template

---

### GET /templates/statistics — テンプレート統計

**認証:** User

**レスポンス (200):**
```json
{
  "total_templates": 50,
  "public_templates": 30,
  "user_templates": 5,
  "server_type_distribution": {
    "paper": 20,
    "vanilla": 15,
    "forge": 15
  }
}
```

**注意:** 非 admin は閲覧可能なテンプレートのみ集計対象。

---

### POST /templates/{template_id}/clone — テンプレート複製

**認証:** Operator または Admin

**リクエスト:**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| name | string (1-100) | ○ |
| description | string | - |
| is_public | bool | - (デフォルト false) |

**処理フロー:**
1. 元テンプレートへのアクセス権確認
2. 元テンプレートの configuration / default_groups をコピーして新規作成
3. テンプレートファイルが存在する場合はコピー

**エラー:**
- 403 Not operator/admin / Access denied to original
- 404 Original not found

---

## テンプレートファイル構造

テンプレートは tar.gz アーカイブとしてサーバー上に保存される。

**含まれる重要ファイル:**
- eula.txt
- ops.json
- whitelist.json
- banned-players.json
- banned-ips.json
- server.properties

**含まれる重要ディレクトリ:**
- plugins/
- mods/
- config/
- datapacks/

## テンプレートのサーバーへの適用

サーバー作成時に `template_id` を指定することで適用される。

**適用処理:**
1. テンプレートの configuration から server.properties を既存設定にマージ
2. テンプレートファイルの tar.gz を展開してサーバーディレクトリに配置
3. default_groups があれば対応するグループを attach

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| テンプレート名 | 1-100 文字 |
| 説明 | 最大 500 文字 |
| minecraft_version | 形式: `\d+\.\d+(\.\d+)?` |
| server_type | 定義済み enum 値 |
