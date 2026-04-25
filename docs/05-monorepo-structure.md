# モノレポ構成・開発環境

v2 の実装リポジトリ構成、Docker Compose 設計、サービス間通信仕様を定義します。

---

## 1. ディレクトリ構成

```
mc-server-dashboard-api/
├── cmd/
│   ├── api/                # HTTP/WebSocket API サーバー
│   │   └── main.go
│   ├── worker/             # ジョブワーカー
│   │   └── main.go
│   └── runner-agent/       # Docker Runner Agent
│       └── main.go
├── internal/
│   ├── domain/             # ドメインモデル・型定義 (サービス共通)
│   ├── db/                 # sqlc 生成コード + DB 接続
│   │   ├── query/          # .sql クエリファイル (sqlc の入力)
│   │   └── gen/            # sqlc 生成 Go コード (コミット対象)
│   ├── api/                # Echo ハンドラ・ミドルウェア・ルーティング
│   ├── worker/             # ジョブワーカー実装
│   ├── runner/             # Runner インターフェース + Docker 実装
│   └── config/             # 環境変数読み込み・設定構造体
├── migrations/             # goose マイグレーションファイル
│   └── YYYYMMDDHHMMSS_*.sql
├── docker/
│   ├── api/
│   │   └── Dockerfile
│   ├── worker/
│   │   └── Dockerfile
│   └── runner-agent/
│       └── Dockerfile
├── docker-compose.yml      # ローカル開発用 (全サービス)
├── docker-compose.test.yml # テスト用 (postgres のみ)
├── sqlc.yaml               # sqlc 設定
├── go.mod
├── go.sum
└── Makefile
```

---

## 2. Go モジュール

モジュール名: `github.com/mmiura-2351/mc-server-dashboard-api`

3サービス (api / worker / runner-agent) が 1つの Go モジュールを共有する。
`internal/` 配下のパッケージをサービス間で共有し、コード重複を排除する。

---

## 3. Docker Compose 構成

### コンテナ一覧

| サービス名 | イメージ | 役割 |
|-----------|---------|------|
| `postgres` | postgres:17-alpine | データストア |
| `redis` | redis:7-alpine | WebSocket pub/sub |
| `api` | ./docker/api | Echo HTTP/WebSocket サーバー |
| `worker` | ./docker/worker | ジョブワーカー |
| `runner-agent` | ./docker/runner-agent | Docker Runner |

### 依存関係

```
api        → postgres, redis
worker     → postgres, runner-agent
runner-agent → (Docker socket)
```

### ポート (ローカル開発)

| サービス | ホストポート | コンテナポート |
|---------|------------|-------------|
| api | 8080 | 8080 |
| postgres | 5432 | 5432 |
| redis | 6379 | 6379 |
| runner-agent | 内部のみ | 8081 |

### 永続ボリューム

| ボリューム | マウント先 | 用途 |
|----------|----------|------|
| `postgres_data` | /var/lib/postgresql/data | DB データ |
| `minecraft_data` | /data (runner-agent) | Minecraft サーバーファイル |
| `/var/run/docker.sock` | /var/run/docker.sock (runner-agent) | Docker API アクセス |

---

## 4. サービス間通信

### Worker → Runner Agent

- **プロトコル**: HTTP/1.1 (JSON)
- **認証**: `Authorization: Bearer <RUNNER_AGENT_TOKEN>`
- **エンドポイント**: `http://runner-agent:8081/`
- **トークン管理**: 環境変数 `RUNNER_AGENT_TOKEN` で両サービスに共有シークレットを渡す

### Runner Agent エンドポイント (内部 API)

Runner Agent が公開する内部 HTTP API。Worker からのみ呼び出される。

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/runners/{id}/create` | コンテナ作成 |
| POST | `/runners/{id}/start` | コンテナ起動 |
| POST | `/runners/{id}/stop` | グレースフル停止 |
| POST | `/runners/{id}/force-stop` | 強制停止 |
| POST | `/runners/{id}/restart` | 再起動 |
| DELETE | `/runners/{id}` | コンテナ削除 |
| POST | `/runners/{id}/command` | コマンド送信 (RCON 経由) |
| GET | `/runners/{id}/logs` | ログ取得 |
| GET | `/runners/{id}/status` | ステータス取得 |

### API → Redis (WebSocket pub/sub)

- チャンネル名: `server:{server_id}:logs`, `server:{server_id}:status`
- Runner Agent → Redis Publish → API が Subscribe してクライアントに配信

---

## 5. 環境変数

### 共通

| 変数名 | 説明 | 例 |
|--------|------|-----|
| `DATABASE_URL` | PostgreSQL 接続文字列 | `postgres://user:pass@postgres:5432/mcdb` |
| `LOG_LEVEL` | ログレベル | `info` |

### api

| 変数名 | 説明 | 例 |
|--------|------|-----|
| `PORT` | HTTP リッスンポート | `8080` |
| `JWT_SECRET` | JWT 署名シークレット | (ランダム文字列) |
| `JWT_EXPIRY_HOURS` | アクセストークン有効期限 (時間) | `1` |
| `REFRESH_TOKEN_EXPIRY_DAYS` | リフレッシュトークン有効期限 (日) | `30` |
| `REDIS_URL` | Redis 接続先 | `redis://redis:6379` |

### worker

| 変数名 | 説明 | 例 |
|--------|------|-----|
| `RUNNER_AGENT_URL` | Runner Agent のベース URL | `http://runner-agent:8081` |
| `RUNNER_AGENT_TOKEN` | Runner Agent 認証トークン | (ランダム文字列) |
| `JOB_POLL_INTERVAL_MS` | ジョブポーリング間隔 (ms) | `500` |

### runner-agent

| 変数名 | 説明 | 例 |
|--------|------|-----|
| `PORT` | HTTP リッスンポート | `8081` |
| `RUNNER_AGENT_TOKEN` | 受信リクエストの認証トークン | (worker と同じ値) |
| `MINECRAFT_DATA_DIR` | Minecraft データ格納ルートディレクトリ | `/data` |
| `REDIS_URL` | ログ/ステータス Publish 先 | `redis://redis:6379` |

---

## 6. Makefile ターゲット (主要)

| ターゲット | 内容 |
|-----------|------|
| `make up` | Docker Compose で全サービス起動 |
| `make down` | 全サービス停止 |
| `make migrate` | goose マイグレーション実行 |
| `make migrate-down` | 1ステップロールバック |
| `make sqlc` | sqlc コード生成 |
| `make test` | テスト実行 (docker-compose.test.yml 使用) |
| `make lint` | golangci-lint 実行 |
| `make build` | 全バイナリビルド |
