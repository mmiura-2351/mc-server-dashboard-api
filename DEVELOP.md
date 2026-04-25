# 開発者ガイド

## 前提条件

| ツール | 用途 | インストール |
|--------|------|------------|
| [Nix](https://nixos.org/download/) | 開発環境管理 | 公式サイト参照 |
| [Docker](https://docs.docker.com/get-docker/) | コンテナ実行 | 公式サイト参照 |
| [direnv](https://direnv.net/) (任意) | シェル自動切替 | `nix profile install nixpkgs#direnv` |

---

## セットアップ

### 1. 開発シェルに入る

```bash
nix develop
```

direnv を使う場合:

```bash
echo "use flake" > .envrc
direnv allow
```

以降は自動でシェルが切り替わるため `nix develop` は不要。

### 2. 環境変数を用意する

```bash
cp .env.example .env
# .env を編集して JWT_SECRET / RUNNER_AGENT_TOKEN 等を設定
```

### 3. コンテナを起動する

```bash
docker compose up -d
```

### 4. DB マイグレーションを実行する

```bash
goose -dir migrations postgres "$DATABASE_URL" up
```

---

## 日常的な開発コマンド

### コンテナ操作

```bash
docker compose up -d          # 全サービス起動
docker compose down           # 全サービス停止
docker compose logs -f api    # api のログをフォロー
```

### コード生成

```bash
sqlc generate                 # SQL → Go コード生成 (internal/db/gen/ に出力)
```

### マイグレーション

```bash
# 適用
goose -dir migrations postgres "$DATABASE_URL" up

# 1ステップ戻す
goose -dir migrations postgres "$DATABASE_URL" down

# 新規マイグレーションファイル作成
goose -dir migrations create <名前> sql
```

### テスト

```bash
# 単体テスト
go test ./...

# DB を使うテスト (docker-compose.test.yml で postgres を起動してから実行)
docker compose -f docker-compose.test.yml up -d
go test ./... -tags integration
docker compose -f docker-compose.test.yml down
```

### Lint

```bash
golangci-lint run
```

### ビルド

```bash
go build ./cmd/api
go build ./cmd/worker
go build ./cmd/runner-agent
```

---

## プロジェクト構成

```
cmd/
  api/           # HTTP/WebSocket API サーバー (Echo)
  worker/        # ジョブワーカー (DB キューポーリング)
  runner-agent/  # Docker Runner Agent

internal/
  domain/        # ドメインモデル・型定義 (サービス共通)
  db/
    query/       # .sql クエリファイル (sqlc の入力)
    gen/         # sqlc 生成 Go コード
  api/           # Echo ハンドラ・ミドルウェア・ルーティング
  worker/        # ジョブワーカー実装
  runner/        # Runner インターフェース + Docker 実装
  config/        # 環境変数読み込み・設定構造体

migrations/      # goose マイグレーションファイル
```

詳細は `docs/05-monorepo-structure.md` を参照。

---

## アーキテクチャ概要

- **api**: クライアントからのリクエストを受け付け、DB に書き込み・Job を投入する
- **worker**: `jobs` テーブルをポーリングし、Runner Agent に HTTP で操作を指示する
- **runner-agent**: Docker SDK 経由で Minecraft コンテナを管理する独立サービス

サービス間通信の詳細は `docs/05-monorepo-structure.md` §6 を参照。

---

## ドキュメント

| ファイル | 内容 |
|----------|------|
| `docs/02-requirements.md` | v2 機能/非機能要件 |
| `docs/03-architecture-direction.md` | アーキテクチャ方針・技術スタック |
| `docs/05-monorepo-structure.md` | リポジトリ構成・Docker Compose・環境変数 |
| `docs/specs/` | 各機能の詳細仕様 |
