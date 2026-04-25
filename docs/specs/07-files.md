# 仕様書: ファイル管理 / 編集履歴

サーバーディレクトリ内のファイルを API 経由で安全に読み書きする機能。
編集履歴のバージョン管理も含む。

## 設計方針

- **Runner 経由のファイルアクセス。** API Core はファイルシステムに直接アクセスしない。すべてのファイル操作は Runner インターフェース経由で行う
- **ゲーム設定はファイルが唯一の真実の源。** `server.properties` 等はこの API で直接編集する（03-servers 参照）
- **編集履歴のストレージはバックアップと共通の抽象化。** ファイル内容のスナップショットはバックアップと同じストレージバックエンドに保存する
- **グループ管理ファイルの保護。** `ops.json` / `whitelist.json` は Groups 機能が管理するため、ファイル API では書き込み・削除を禁止する
- **Organization スコープ。** サーバーに属するファイルは同じ Organization のメンバーのみアクセス可能

---

## データモデル

### FileEditHistory

ファイル書き込み前に自動保存されるスナップショット。

| フィールド | 型 | 制約 | 説明 |
|-----------|-----|------|------|
| id | UUID | PK | - |
| server_id | UUID | FK(servers.id), NOT NULL | - |
| file_path | string(500) | NOT NULL | サーバールートからの相対パス |
| version_number | int | NOT NULL | バージョン番号 (1始まり、ファイル毎に連番) |
| storage_backend | enum | NOT NULL | local / s3_compatible |
| storage_key | string(1000) | NOT NULL | ストレージ上の識別キー |
| file_size_bytes | bigint | NOT NULL | バイト数 |
| content_hash | string(64) | NOT NULL | SHA256 ハッシュ (重複検出用) |
| editor_user_id | UUID | FK(users.id), ON DELETE SET NULL | 編集者 |
| description | text | - | 変更メモ |
| created_at | datetime(tz) | NOT NULL | - |

**UNIQUE 制約:** (server_id, file_path, version_number)

---

## FileInfoResponse

```json
{
  "name": "server.properties",
  "path": "server.properties",
  "type": "text | binary | directory | other",
  "is_directory": false,
  "size_bytes": 1024,
  "modified_at": "ISO8601"
}
```

---

## ファイル管理エンドポイント

### GET /api/v2/organizations/{org_id}/servers/{server_id}/files/{path} — ディレクトリ一覧 / ファイル情報

**認証:** `file.read` 権限

`{path}` がディレクトリの場合は配下の一覧を返し、ファイルの場合はそのファイル情報を返す。
`{path}` を省略するとルートディレクトリの一覧を返す。

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| type | enum | text / binary / directory / other でフィルタ |

**レスポンス (200) — ディレクトリの場合:**
```json
{
  "current_path": "plugins/",
  "files": [
    {
      "name": "EssentialsX.jar",
      "path": "plugins/EssentialsX.jar",
      "type": "binary",
      "is_directory": false,
      "size_bytes": 2097152,
      "modified_at": "ISO8601"
    }
  ],
  "total_count": 15
}
```

**レスポンス (200) — ファイルの場合:** `FileInfoResponse`

**エラー:**
- 404 `Path not found`

---

### GET /api/v2/organizations/{org_id}/servers/{server_id}/files/{path}/content — ファイル内容読み取り

**認証:** `file.read` 権限

**クエリパラメータ:**
| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|---------|------|
| encoding | string | (自動検出) | 文字エンコーディング指定 |

**レスポンス (200) — テキストファイル:**
```json
{
  "content": "string",
  "encoding": "utf-8",
  "file_info": { ...FileInfoResponse }
}
```

**レスポンス (200) — バイナリファイル:**
```json
{
  "content": "base64エンコード文字列",
  "encoding": "base64",
  "file_info": { ...FileInfoResponse }
}
```

**エンコード自動検出:**
1. chardet で検出、精度 > 70% であればその結果を使用
2. フォールバック順: utf-8 → shift_jis → euc-jp → cp932 → latin1

**エラー:**
- 404 `File not found`
- 400 `Path is a directory. Use the directory listing endpoint.`

---

### GET /api/v2/organizations/{org_id}/servers/{server_id}/files/{path}/download — ダウンロード

**認証:** `file.read` 権限

**レスポンス (200):** バイナリストリーム

- ファイルの場合: そのままストリーミング
- ディレクトリの場合: ZIP アーカイブとして返却 (`Content-Type: application/zip`)

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/files/upload — アップロード

**認証:** `file.write` 権限

**リクエスト (multipart/form-data):**
| フィールド | 型 | 必須 | 説明 |
|-----------|-----|-----|------|
| file | UploadFile | ○ | - |
| destination_path | string | - | アップロード先パス (デフォルト: ルート) |
| extract_if_archive | bool | - (デフォルト false) | ZIP / tar.gz を展開するか |

**レスポンス (201):**
```json
{
  "file": { ...FileInfoResponse },
  "extracted_files": ["plugins/example.jar"]
}
```

**アーカイブ安全性検証 (`extract_if_archive=true` 時):**
- シンボリックリンクを含むエントリは禁止
- ハードリンクを含むエントリは禁止
- アーカイブ内のパスがサーバーディレクトリ外を指していないことを確認

**エラー:**
- 400 `Destination path is outside server directory`
- 422 `Archive contains unsafe entries`

---

### PUT /api/v2/organizations/{org_id}/servers/{server_id}/files/{path} — ファイル書き込み

**認証:** `file.write` 権限

**書き込み禁止ファイル:** `ops.json` / `whitelist.json`（Groups 機能が管理）

**リクエスト (JSON):**
| フィールド | 型 | 必須 | 説明 |
|-----------|-----|-----|------|
| content | string | ○ | ファイル内容 |
| encoding | string | - (デフォルト utf-8) | 書き込みエンコーディング |
| create_history | bool | - (デフォルト true) | 書き込み前に履歴スナップショットを作成 |
| description | string | - | 変更メモ (履歴に記録) |

**レスポンス (200):**
```json
{
  "file": { ...FileInfoResponse },
  "history_created": true,
  "version_number": 5
}
```

**処理フロー:**
1. 書き込み禁止ファイルでないことを確認
2. `create_history=true` の場合、現在の内容をスナップショットとして保存 (SHA256 が前バージョンと同一なら保存しない)
3. Runner 経由でファイルに書き込み

**稼働中サーバーへの変更と設定反映:**
- `server.properties` 等のゲーム設定ファイルは稼働中でも書き込み可能
- ただし `server.properties` の変更はサーバーを再起動するまで反映されない（Minecraft の仕様）
- 即時反映が必要な設定は、別途 `/command` エンドポイントで RCON コマンドを送信する
- インフラ設定 (メモリ/CPU) は DB 管理であり、このエンドポイントでは変更できない (specs/03-servers.md 参照)

**エラー:**
- 403 `This file is managed by Groups and cannot be written directly`
- 400 `Path is outside server directory`

---

### DELETE /api/v2/organizations/{org_id}/servers/{server_id}/files/{path} — ファイル削除

**認証:** `file.delete` 権限

**削除禁止ファイル:** `ops.json` / `whitelist.json` / `eula.txt`（常に禁止）

**リクエスト (JSON):** (任意)
```json
{ "recursive": true }
```

ディレクトリを削除する場合は `recursive: true` が必要。

**レスポンス (200):**
```json
{ "message": "Deleted successfully", "path": "string" }
```

**処理フロー:**
1. 削除禁止ファイルでないことを確認
2. ディレクトリかつ `recursive=false` の場合は 400
3. Runner 経由で削除
4. 対象ファイルの FileEditHistory は保持（削除しない）
5. 監査ログ記録

**エラー:**
- 403 `This file cannot be deleted`
- 400 `Directory is not empty. Use recursive=true to delete.`

---

### PATCH /api/v2/organizations/{org_id}/servers/{server_id}/files/{path}/rename — リネーム

**認証:** `file.write` 権限

**リクエスト (JSON):**
```json
{ "new_name": "string (1-255文字)" }
```

`new_name` にパスセパレータ (`/`, `\`) を含めてはならない（同ディレクトリ内でのリネームのみ）。

**レスポンス (200):**
```json
{
  "old_path": "plugins/old-name.jar",
  "new_path": "plugins/new-name.jar",
  "file": { ...FileInfoResponse }
}
```

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/files/{path}/mkdir — ディレクトリ作成

**認証:** `file.write` 権限

**リクエスト (JSON):**
```json
{ "name": "string (1-100文字)" }
```

**レスポンス (201):**
```json
{ "directory": { ...FileInfoResponse } }
```

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/files/search — ファイル検索

**認証:** `file.read` 権限

**リクエスト (JSON):**
| フィールド | 型 | 制約 | 必須 |
|-----------|-----|------|-----|
| query | string | 1文字以上 | ○ |
| search_path | string | - | 検索対象ディレクトリ (デフォルト: ルート) |
| type | enum | text / binary / directory / other | - |
| include_content | bool | - (デフォルト false) | ファイル内容を全文検索するか |
| max_results | int | 1-200 | - (デフォルト 50) |

**タイムアウト:** 30 秒。超過した場合は 408 を返す。

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

`include_content=false` の場合は `matches` は空、ファイル名のみでマッチ。

**エラー:**
- 408 `Search timed out. Try narrowing the search path or disabling content search.`

---

## ファイル編集履歴エンドポイント

### GET /api/v2/organizations/{org_id}/servers/{server_id}/files/{path}/history — 履歴一覧

**認証:** `file.read` 権限

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| page | int | 1 |
| page_size | int (1-100) | 20 |

**レスポンス (200):**
```json
{
  "file_path": "server.properties",
  "total_versions": 5,
  "history": [
    {
      "id": "uuid",
      "version_number": 5,
      "file_size_bytes": 1024,
      "content_hash": "sha256...",
      "editor_username": "string | null",
      "description": "null",
      "created_at": "ISO8601"
    }
  ]
}
```

---

### GET /api/v2/organizations/{org_id}/servers/{server_id}/files/{path}/history/{version} — バージョン内容取得

**認証:** `file.read` 権限

**レスポンス (200):**
```json
{
  "file_path": "server.properties",
  "version_number": 3,
  "content": "string",
  "encoding": "utf-8",
  "editor_username": "string | null",
  "description": null,
  "created_at": "ISO8601"
}
```

---

### POST /api/v2/organizations/{org_id}/servers/{server_id}/files/{path}/history/{version}/restore — バージョン復元

**認証:** `file.write` 権限

**リクエスト (JSON):**
```json
{
  "create_history_before_restore": true,
  "description": "string | null"
}
```

**レスポンス (200):**
```json
{
  "file": { ...FileInfoResponse },
  "history_created": true,
  "restored_from_version": 3,
  "new_version_number": 6
}
```

**処理フロー:**
1. `create_history_before_restore=true` の場合、現在の内容をスナップショットとして保存
2. 指定バージョンの内容をストレージから取得
3. Runner 経由でファイルに書き込み
4. 復元操作を新バージョンとして履歴に記録

---

### DELETE /api/v2/organizations/{org_id}/servers/{server_id}/files/{path}/history/{version} — バージョン削除

**認証:** `file.delete` 権限

**レスポンス (200):**
```json
{ "deleted_version": 3 }
```

**処理フロー:**
1. ストレージバックエンドからスナップショットファイルを削除
2. DB レコードを削除

---

### GET /api/v2/organizations/{org_id}/servers/{server_id}/files/history/stats — 履歴統計

**認証:** `file.read` 権限

**レスポンス (200):**
```json
{
  "server_id": "uuid",
  "total_files_with_history": 15,
  "total_versions": 87,
  "total_storage_bytes": 5242880,
  "oldest_version_at": "ISO8601",
  "most_edited_file": "server.properties",
  "most_edited_file_versions": 23
}
```

---

## セキュリティ要件

### パストラバーサル防止

Runner 側で強制する。API Core でも二重に検証する。

- `../` を含むパスは拒否
- 絶対パスは拒否 (先頭が `/` のパス)
- バックスラッシュは拒否
- ヌルバイトを含むパスは拒否
- サーバーディレクトリのルートから外に出るパスは拒否

### 保護ファイル

| ファイル | 理由 | 扱い |
|---------|------|------|
| `ops.json` | Groups 機能が管理 | 書き込み・削除禁止 |
| `whitelist.json` | Groups 機能が管理 | 書き込み・削除禁止 |
| `eula.txt` | 誤削除防止 | 削除禁止、書き込みは `file.write` 権限で可 |

---

## 編集履歴の保存ルール

1. **重複スキップ:** SHA256 ハッシュが直前バージョンと同一の場合はスナップショットを作成しない
2. **バージョン上限:** サーバー設定で保持するバージョン数の上限を設定可能 (デフォルト 50/ファイル)。上限超過時は最古バージョンから削除
3. **ストレージ:** バックアップと同じストレージバックエンドを使用 (05-backups 参照)

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| ファイル名 / 新名前 | 1-255 文字、パスセパレータを含まない |
| ディレクトリ名 | 1-100 文字 |
| 検索クエリ | 1文字以上、最大 200 文字 |
| max_results | 1-200 |
| page_size (履歴) | 1-100 |

---

## 監査イベント一覧

| イベント | action 値 | resource_type |
|--------|-----------|---------------|
| ファイル書き込み | `file_write` | file |
| ファイル削除 | `file_delete` | file |
| ファイルリネーム | `file_rename` | file |
| ファイルアップロード | `file_upload` | file |
| バージョン復元 | `file_version_restore` | file |
| バージョン削除 | `file_version_delete` | file |
