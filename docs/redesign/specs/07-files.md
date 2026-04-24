# 仕様書: ファイル管理 / 編集履歴

サーバーディレクトリ内のファイルを API 経由で安全に読み書きする機能。
編集履歴のバージョン管理も含む。

## データモデル

### FileEditHistory

| フィールド | 型 | 制約 | 説明 |
|-----------|-----|------|------|
| id | int | PK | - |
| server_id | int | FK(servers.id), NOT NULL | - |
| file_path | string(500) | NOT NULL | サーバールートからの相対パス |
| version_number | int | NOT NULL | バージョン番号 (1始まり、ファイル毎) |
| backup_file_path | string(500) | NOT NULL | バックアップファイルの絶対パス |
| file_size | bigint | NOT NULL | バイト数 |
| content_hash | string(64) | - | SHA256 ハッシュ (重複検出用) |
| editor_user_id | int | FK(users.id), ON DELETE SET NULL | 編集者 |
| created_at | datetime | NOT NULL | - |
| description | text | - | 変更メモ |

---

## ファイル管理エンドポイント

### GET /servers/{server_id}/files/{path} — ファイル/ディレクトリ一覧

**認証:** User

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| file_type | enum | text / binary / directory / other でフィルタ |

**レスポンス (200):** `FileListResponse`
```json
{
  "files": [
    {
      "name": "server.properties",
      "path": "server.properties",
      "type": "text",
      "is_directory": false,
      "size": 1024,
      "modified": "ISO8601",
      "permissions": { "read": true, "write": true, "execute": false }
    }
  ],
  "current_path": "plugins/",
  "total_files": 15
}
```

**エラー:**
- 404 Server / path not found
- 403 Access denied

---

### GET /servers/{server_id}/files/{path}/read — ファイル内容読み取り

**認証:** User

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| encoding | string | utf-8 |
| image | bool | false |

**レスポンス (200):**
```json
{
  "content": "string (テキスト or base64)",
  "encoding": "utf-8",
  "file_info": { ...FileInfoResponse },
  "is_image": false,
  "image_data": null
}
```

**画像の場合:** `image=true` で `image_data` に base64 エンコードされたデータを返す。

**エンコード検出:** chardet で自動検出。検出精度 > 70% の場合はその結果を使用。
フォールバック順: utf-8, shift_jis, euc-jp, iso-2022-jp, cp932, latin1, ascii

---

### GET /servers/{server_id}/files/{path}/download — ファイルダウンロード

**認証:** User

**レスポンス (200):** バイナリストリーム

**ディレクトリの場合:** ZIP アーカイブとして返却

---

### POST /servers/{server_id}/files/upload — ファイルアップロード

**認証:** User (can_modify_files 権限)

**リクエスト (multipart/form-data):**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| file | UploadFile | ○ |
| destination_path | string | - (デフォルト ルート) |
| extract_if_archive | bool | - (デフォルト false) |

**レスポンス (200):**
```json
{
  "message": "string",
  "file": { ...FileInfoResponse },
  "extracted_files": ["plugins/example.jar"]
}
```

**処理フロー:**
1. 宛先パスにファイルを保存
2. `extract_if_archive=true` かつアーカイブ形式 → 展開
3. ファイル履歴エントリを作成

---

### PUT /servers/{server_id}/files/{path} — ファイル書き込み

**認証:** User (can_modify_files 権限)

**リクエスト:**
| フィールド | 型 | 必須 |
|-----------|-----|-----|
| content | string | ○ |
| encoding | string | - (デフォルト utf-8) |
| create_backup | bool | - (デフォルト true) |

**レスポンス (200):**
```json
{
  "message": "string",
  "file": { ...FileInfoResponse },
  "backup_created": true
}
```

**処理フロー:**
1. `create_backup=true` の場合、先に現在の内容をバックアップ (FileEditHistory)
2. 指定エンコードでファイルに書き込み
3. 履歴レコードを作成

---

### DELETE /servers/{server_id}/files/{path} — ファイル削除

**認証:** User (can_modify_files 権限)

**処理フロー:**
1. 制限ファイル (ops.json, whitelist.json, eula.txt 等) は admin 以外は削除不可
2. ディレクトリの場合は再帰的に削除
3. 監査ログ記録

**レスポンス (200):**
```json
{ "message": "string" }
```

---

### PATCH /servers/{server_id}/files/{path}/rename — リネーム

**認証:** User (can_modify_files 権限)

**リクエスト:**
```json
{ "new_name": "string (1-255文字)" }
```

**制約:** new_name にパスセパレータ (`/`, `\`) を含めてはならない

**レスポンス (200):**
```json
{
  "message": "string",
  "old_path": "string",
  "new_path": "string",
  "file": { ...FileInfoResponse }
}
```

---

### POST /servers/{server_id}/files/{path}/directories — ディレクトリ作成

**認証:** User (can_modify_files 権限)

**リクエスト:**
```json
{ "name": "string (1-100文字)" }
```

**レスポンス (200):**
```json
{
  "message": "string",
  "directory": { ...FileInfoResponse }
}
```

---

### POST /servers/{server_id}/files/search — ファイル検索

**認証:** User

**リクエスト:**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| query | string | 最小 1 文字 | ○ |
| file_type | enum | - | - |
| include_content | bool | - | - (デフォルト false) |
| max_results | int | 1-200 | - (デフォルト 50) |

**レスポンス (200):**
```json
{
  "results": [
    {
      "file": { ...FileInfoResponse },
      "matches": ["マッチした行の内容"],
      "match_count": 3
    }
  ],
  "query": "string",
  "total_results": 10,
  "search_time_ms": 150
}
```

---

## ファイル編集履歴エンドポイント

### GET /servers/{server_id}/files/{path}/history — 編集履歴一覧

**認証:** User

**クエリパラメータ:** `limit` (1-100, デフォルト 20)

**レスポンス (200):**
```json
{
  "file_path": "server.properties",
  "total_versions": 5,
  "history": [
    {
      "id": 1,
      "server_id": 1,
      "file_path": "server.properties",
      "version_number": 5,
      "backup_file_path": "string",
      "file_size": 1024,
      "content_hash": "sha256...",
      "editor_user_id": 1,
      "editor_username": "string",
      "created_at": "ISO8601",
      "description": null
    }
  ]
}
```

---

### GET /servers/{server_id}/files/{path}/history/{version} — 特定バージョン内容取得

**認証:** User

**レスポンス (200):**
```json
{
  "file_path": "server.properties",
  "version_number": 3,
  "content": "string",
  "encoding": "utf-8",
  "created_at": "ISO8601",
  "editor_username": "string",
  "description": null
}
```

---

### POST /servers/{server_id}/files/{path}/history/{version}/restore — バージョン復元

**認証:** User (can_modify_files 権限)

**リクエスト:**
```json
{
  "create_backup_before_restore": true,
  "description": "string|null"
}
```

**レスポンス (200):**
```json
{
  "message": "string",
  "file": { ...FileInfoResponse },
  "backup_created": true,
  "restored_from_version": 3
}
```

**処理フロー:**
1. `create_backup_before_restore=true` の場合、現在の内容を新バージョンとして保存
2. 指定バージョンの内容を現在のファイルに書き戻す
3. 復元操作を履歴エントリとして記録

---

### DELETE /servers/{server_id}/files/{path}/history/{version} — バージョン削除

**認証:** Admin

**レスポンス (200):**
```json
{
  "message": "string",
  "deleted_version": 3
}
```

**処理フロー:**
1. バックアップファイルをディスクから削除
2. DB レコードを削除

---

### GET /servers/{server_id}/files/history/statistics — ファイル履歴統計

**認証:** User

**レスポンス (200):**
```json
{
  "server_id": 1,
  "total_files_with_history": 15,
  "total_versions": 87,
  "total_storage_used": 5242880,
  "oldest_version_date": "ISO8601",
  "most_edited_file": "server.properties",
  "most_edited_file_versions": 23
}
```

---

## セキュリティ要件

**パストラバーサル防止:**
- すべてのパス操作でサーバーディレクトリ外に出ないことを検証
- `../` を含むパスは拒否
- 絶対パスは拒否
- バックスラッシュは拒否

**制限ファイル (admin 以外は削除不可):**
- ops.json
- whitelist.json
- eula.txt
- その他 admin 限定ファイル

**アーカイブ検証 (アップロード時):**
- シンボリックリンクは禁止
- ハードリンクは禁止
- アーカイブ内のパスがサーバーディレクトリ外を指していないことを確認

---

## 編集履歴の保存ルール

1. **重複検出:** SHA256 ハッシュが直前バージョンと同じ場合はバックアップを作成しない
2. **バージョン上限:** ファイル毎に保持するバージョン数の上限が設定可能 (超過時は古いものから削除)
3. **ストレージ:** バックアップは独立したディレクトリ (`file_history/`) に保存

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| ファイル名 | 最大 255 文字 |
| ディレクトリ名 | 1-100 文字 |
| 検索クエリ | 最小 1 文字 |
| max_results | 1-200 |
| 履歴取得件数 | 1-100 |
