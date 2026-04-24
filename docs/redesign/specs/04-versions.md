# 仕様書: バージョン管理 (Versions)

Minecraft サーバー JAR のバージョン情報を DB に永続化し、外部 API への依存を排除する。

## 背景・設計方針

- v1 の問題: 毎リクエストで Mojang/PaperMC の外部 API を叩いており、応答に 4-5 秒かかる
- v2 方針: バージョン情報を DB に保存し、バックグラウンドで定期更新する (10-50ms で応答)

## データモデル

### MinecraftVersion

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| server_type | string(20) | NOT NULL | - | vanilla / paper / forge |
| version | string(50) | NOT NULL | - | 例: "1.21.1" |
| download_url | text | NOT NULL | - | ダウンロード URL |
| release_date | datetime | - | NULL | リリース日 |
| is_stable | bool | NOT NULL | true | 安定版フラグ |
| build_number | int | - | NULL | PaperMC のビルド番号 |
| is_active | bool | NOT NULL | true | 有効フラグ |
| created_at | datetime | NOT NULL | utcnow() | - |
| updated_at | datetime | NOT NULL | utcnow() | - |

**インデックス:**
- UNIQUE: (server_type, version)
- INDEX: (server_type, is_active)
- INDEX: (version, is_active)

### VersionUpdateLog

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | int | PK | - | - |
| update_type | string(20) | NOT NULL | - | manual / scheduled |
| server_type | string(20) | - | NULL | NULL = 全種類更新 |
| versions_added | int | - | 0 | 追加数 |
| versions_updated | int | - | 0 | 更新数 |
| versions_removed | int | - | 0 | 削除数 |
| execution_time_ms | int | - | NULL | 実行時間 (ms) |
| external_api_calls | int | - | 0 | 外部 API コール数 |
| status | string(20) | NOT NULL | - | success / failed / partial |
| error_message | text | - | NULL | エラー詳細 |
| executed_by_user_id | int | - | NULL | 手動実行ユーザー |
| started_at | datetime | NOT NULL | utcnow() | - |
| completed_at | datetime | - | NULL | - |

---

## エンドポイント

### GET /api/versions/supported — サポートバージョン一覧

**認証:** 不要

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| server_type | enum | vanilla / paper / forge でフィルタ (任意) |

**レスポンス (200):** `List[MinecraftVersionResponse]`
```json
[
  {
    "version": "1.20.1",
    "server_type": "paper",
    "download_url": "https://...",
    "is_supported": true,
    "release_date": "ISO8601",
    "is_stable": true,
    "build_number": 196
  }
]
```

**実装:** DB の `is_active=true` レコードを取得。応答目標 10-50ms。

---

### POST /api/versions/update — バージョン情報を手動更新

**認証:** Admin

**クエリパラメータ:**
| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|---------|------|
| server_types | List[enum] | 全種類 | 更新対象サーバータイプ |
| force_refresh | bool | false | キャッシュを無視して強制更新 |

**レスポンス (200):** `VersionUpdateResult`
```json
{
  "success": true,
  "message": "string",
  "log_id": 42,
  "versions_added": 3,
  "versions_updated": 1,
  "versions_removed": 0,
  "execution_time_ms": 2500,
  "errors": []
}
```

**処理フロー:**
1. 実行中の更新があればスキップ
2. VersionUpdateLog を作成 (status=running)
3. 各 server_type ごとに外部 API からバージョン情報を取得
4. DB と比較して追加/更新/非アクティブ化を実行
5. VersionUpdateLog を更新 (status=success/failed)

**エラー:**
- 403 Not admin

---

### GET /api/versions/scheduler/status — スケジューラー状態

**認証:** Admin

**レスポンス (200):**
```json
{
  "is_running": true,
  "last_update": "ISO8601|null",
  "next_update": "ISO8601|null",
  "update_interval_hours": 24,
  "last_error": null
}
```

**エラー:**
- 403 Not admin

---

### GET /api/versions/stats — バージョン統計

**認証:** 不要

**レスポンス (200):**
```json
{
  "total_versions": 300,
  "active_versions": 250,
  "by_server_type": {
    "vanilla": { "total": 100, "active": 80 },
    "paper": { "total": 150, "active": 130 },
    "forge": { "total": 50, "active": 40 }
  }
}
```

---

### GET /api/versions/{server_type} — 特定タイプのバージョン一覧

**認証:** 不要

**レスポンス (200):** `List[MinecraftVersionResponse]` (バージョン降順)

---

### GET /api/versions/{server_type}/{version} — 特定バージョン詳細

**認証:** 不要

**レスポンス (200):** `MinecraftVersionResponse`

**エラー:**
- 404 Version not found

---

## バージョン更新ロジック

### 外部 API ソース
| server_type | 外部 API |
|-------------|---------|
| vanilla | Mojang (piston-meta.mojang.com) |
| paper | PaperMC API (api.papermc.io) |
| forge | Maven metadata |

### 更新処理の流れ
```
1. 外部 API からバージョン一覧を取得
2. DB の現在バージョン一覧を取得
3. 比較:
   - 外部 API にあって DB にない → 追加 (INSERT)
   - 両方にあって差分がある → 更新 (UPDATE)
   - 外部 API にあって DB にない旧バージョン → is_active=false に更新 (論理削除)
4. VersionUpdateLog を更新 (added, updated, removed カウント)
```

### スケジューラー
- デフォルト更新間隔: 24 時間
- アプリ起動時に自動起動
- 手動トリガー可能 (Admin)

### 最小サポートバージョン
- 1.8.0 以上 (それ未満は除外)
