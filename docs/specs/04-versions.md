# 仕様書: Minecraft バージョン管理

## 設計方針

- **DBキャッシュ。** バージョン情報は DB に永続化し、外部 API へのリアルタイム問い合わせをなくす (応答目標 10-50ms)
- **バックグラウンド自動更新。** スケジューラーが定期的に外部 API と同期する
- **システムグローバル。** バージョン情報は Organization に依存しない共有リソース
- **Runner に渡すための情報。** `download_url` は API Core が使うのではなく、サーバー作成時に Runner へ渡すために保持する
- **Java バージョンは持たない。** Minecraft バージョンから Java バージョンへのマッピングは固定の対応関係であり、Runner の内部ロジックが担う
- **監査ログは VersionUpdateLog で代替。** バージョン更新操作は `audit_logs` には記録しない。`VersionUpdateLog` が実行者・結果・件数を保持するため、監査の役割を担う

---

## データモデル

### MinecraftVersion

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| server_type | enum | NOT NULL | - | 下記参照 |
| version | string(50) | NOT NULL | - | ゲームバージョン (例: "1.21.1" / "26.1" / "26.1.2") |
| build_number | int | - | NULL | ビルド番号 (Paper 等のみ) |
| download_url | text | NOT NULL | - | JAR ダウンロード URL (Runner に渡す) |
| release_date | datetime(tz) | - | NULL | リリース日時 |
| is_stable | bool | NOT NULL | true | 安定版フラグ |
| is_active | bool | NOT NULL | true | 選択可能フラグ (false = 非推奨/廃止) |
| created_at | datetime(tz) | NOT NULL | now() | - |
| updated_at | datetime(tz) | NOT NULL | now() | - |

**UNIQUE 制約:** (server_type, version, build_number)

**server_type 値:**

| 値 | 外部 API ソース |
|----|---------------|
| `vanilla` | Mojang (piston-meta.mojang.com) |
| `paper` | PaperMC API (api.papermc.io) |
| `folia` | PaperMC API |
| `spigot` | SpigotMC (hub.spigotmc.org) |
| `purpur` | Purpur API (api.purpurmc.org) |
| `forge` | MinecraftForge Maven |
| `fabric` | Fabric Meta API (meta.fabricmc.net) |
| `neoforge` | NeoForge Maven |

---

### VersionUpdateLog

バージョン更新処理の実行履歴。

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| trigger | enum | NOT NULL | - | scheduled / manual |
| server_types | JSON | - | NULL | 更新対象 (NULL = 全種類) |
| versions_added | int | NOT NULL | 0 | 追加件数 |
| versions_updated | int | NOT NULL | 0 | 更新件数 |
| versions_deactivated | int | NOT NULL | 0 | 非アクティブ化件数 |
| execution_time_ms | int | - | NULL | 処理時間 (ms) |
| status | enum | NOT NULL | - | running / success / failed / partial |
| error_message | text | - | NULL | エラー詳細 |
| triggered_by_user_id | UUID | FK(users.id), ON DELETE SET NULL | NULL | 手動実行者 (scheduled の場合 NULL) |
| started_at | datetime(tz) | NOT NULL | now() | - |
| completed_at | datetime(tz) | - | NULL | - |

---

## エンドポイント

### GET /api/v2/minecraft/versions — バージョン一覧

**認証:** 不要

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| server_type | enum | フィルタ (複数指定可) |
| is_stable | bool | 安定版のみに絞り込み |
| game_version | string | 特定ゲームバージョンでフィルタ (例: "1.21.1") |

**レスポンス (200):**
```json
{
  "versions": [
    {
      "id": "uuid",
      "server_type": "paper",
      "version": "26.1",
      "build_number": 52,
      "download_url": "https://...",
      "release_date": "ISO8601 | null",
      "is_stable": true
    }
  ],
  "total_count": 250,
  "last_updated_at": "ISO8601"
}
```

`is_active=false` のバージョンは除外する。バージョン降順でソート。

---

### GET /api/v2/minecraft/versions/{server_type}/{version} — バージョン詳細

**認証:** 不要

**クエリパラメータ:**
| パラメータ | 型 | 説明 |
|-----------|-----|------|
| build_number | int | ビルド番号を指定 (paper/folia 等のみ有効) |

**ビルド番号の扱い:**
- `build_number` を省略した場合、指定 `server_type` / `version` の中で最も大きい `build_number` を返す (最新ビルド)
- vanilla 等 `build_number` が NULL のサーバータイプでは `build_number` クエリパラメータは無視する

**レスポンス (200):**
```json
{
  "id": "uuid",
  "server_type": "paper",
  "version": "1.21.1",
  "build_number": 196,
  "download_url": "https://...",
  "release_date": "ISO8601 | null",
  "is_stable": true
}
```

**エラー:**
- 404 `Version not found`
- 404 `Build not found` (指定した build_number が存在しない場合)

---

### POST /api/v2/minecraft/versions/refresh — 手動更新トリガー

**認証:** User (JWT)

**Note:** バージョン情報はゲームプレイに影響しない公開情報であるため、全認証ユーザーが実行可能とする。クールダウンにより外部 API への過剰リクエストを防止する。

**クールダウン:** 1 時間に 1 回まで実行可能 (全ユーザー共通カウンター)

**クエリパラメータ:**
| パラメータ | 型 | デフォルト | 説明 |
|-----------|-----|---------|------|
| server_types | string[] | 全種類 | 更新対象 server_type |

**レスポンス (202):**
```json
{
  "log_id": "uuid",
  "message": "Version update started",
  "started_at": "ISO8601"
}
```

**処理フロー:**
1. クールダウン確認 → 前回の実行から 1 時間未満なら 429
2. VersionUpdateLog を作成 (`status=running`, `trigger=manual`)
3. バックグラウンドジョブとして更新処理を起動
4. すぐに 202 を返す (完了を待たない)

**エラー:**
- 429 `Version update was recently triggered. Try again later.`

---

### GET /api/v2/minecraft/versions/update-logs — 更新ログ一覧

**認証:** User (JWT)

**クエリパラメータ:**
| パラメータ | 型 | デフォルト |
|-----------|-----|---------|
| page | int | 1 |
| page_size | int (1-50) | 20 |

**レスポンス (200):**
```json
{
  "logs": [
    {
      "id": "uuid",
      "trigger": "scheduled | manual",
      "status": "success | failed | partial | running",
      "versions_added": 3,
      "versions_updated": 1,
      "versions_deactivated": 0,
      "execution_time_ms": 2300,
      "error_message": null,
      "triggered_by_username": "string | null",
      "started_at": "ISO8601",
      "completed_at": "ISO8601 | null"
    }
  ],
  "total_count": 100
}
```

---

### GET /api/v2/minecraft/versions/stats — バージョン統計

**認証:** 不要

**レスポンス (200):**
```json
{
  "total_active_versions": 250,
  "by_server_type": {
    "vanilla": 80,
    "paper": 120,
    "fabric": 50
  },
  "last_updated_at": "ISO8601 | null",
  "scheduler": {
    "next_update_at": "ISO8601",
    "update_interval_hours": 24
  }
}
```

---

## バージョン更新ロジック

### 更新処理の流れ

```
1. 対象 server_type ごとに外部 API からバージョン一覧を取得
2. DB の現在バージョン一覧と比較:
   - 外部 API にあって DB にない          → INSERT (is_active=true)
   - 両方にあって download_url 等に差分   → UPDATE
   - DB にあって外部 API から消えた       → is_active=false に更新
3. VersionUpdateLog を更新 (added / updated / deactivated カウント)
```

### バージョン形式

2025年より Mojang がバージョン形式を変更した。両形式を並存してサポートする。

| 形式 | パターン | 例 | 対象期間 |
|------|---------|-----|---------|
| 旧形式 | `1.\d+(\.\d+)?` | `1.21.1`, `1.20.4` | ～2024年 |
| 新形式 | `\d{2}.\d+(\.\d+)?` | `25.3`, `26.1`, `26.1.2` | 2025年～ |

新形式の構造: `YY.DROP[.PATCH]`
- `YY` — リリース年の下2桁 (25 = 2025, 26 = 2026)
- `DROP` — その年の何番目のアップデートか
- `PATCH` — ホットフィックス番号 (省略可)

バリデーション正規表現 `\d+\.\d+(\.\d+)?` は両形式を網羅する。

### 最小サポートバージョン

旧形式: **1.8.0** 以上のみ取得・保存する。
新形式: すべて取得・保存する (2025年以降の全バージョン)。

### スケジューラー

- 更新間隔: **24 時間** (環境変数で変更可能)
- アプリ起動時に自動起動
- 実行中の更新が存在する場合はスキップ

### 外部 API 障害時の挙動

- 外部 API へのリクエストはタイムアウト 10 秒
- 1つの server_type の取得が失敗しても他の server_type は続行する
- 部分的に成功した場合は `status=partial` で記録
- DB の既存データは保持し、失敗した server_type 分のみ更新をスキップする

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| server_type | 定義済み enum 値 |
| version | `\d+\.\d+(\.\d+)?` 形式 (旧: `1.X.Y` / 新: `YY.DROP[.PATCH]`) |
| page_size (update-logs) | 1-50 |
