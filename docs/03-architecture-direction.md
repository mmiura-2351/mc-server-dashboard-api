# v2 アーキテクチャ方針

`02-requirements.md` の要件を満たすアーキテクチャ方針です。技術スタックを含む主要事項は確定済みです。

## 1. 全体構成 (コンテナ構成)

```
        ┌────────────────────┐
        │  Web UI / CLI /    │
        │  External API User │
        └─────────┬──────────┘
                  │ (HTTPS, JWT)
        ┌─────────▼──────────┐
        │   [api コンテナ]    │  ← ステートレス / 水平スケール
        │   Echo (Go)        │
        └──┬──────┬──────┬───┘
           │      │      │
       SQL │    Redis    │ Redis pub/sub
           │   pub/sub   │ (WebSocket 配信)
     ┌─────▼┐  ┌──▼──────┐
     │[pg]  │  │[redis]  │
     │(PG)  │  │         │
     └──┬───┘  └─────────┘
        │ SQL (job polling)
        │
     ┌──▼──────────────┐
     │ [worker コンテナ] │  ← DB キューをポーリング
     │  Job Worker (Go) │
     └──────────┬───────┘
                │ HTTP + Bearer Token
     ┌──────────▼───────────┐
     │ [runner-agent コンテナ]│  ← 独立デプロイ可能
     │  Runner Agent (Go)   │
     └──────────┬────────────┘
                │ Docker SDK (/var/run/docker.sock)
     ┌──────────▼────────────┐
     │  Minecraft コンテナ    │  ← JVM in sandbox
     └───────────────────────┘
```

- **api**: HTTP/WebSocket エンドポイント、認可、DB 読み書き。Redis pub/sub で WebSocket をマルチレプリカ対応
- **worker**: DB の `jobs` テーブルをポーリングし、Runner Agent に HTTP で指示を出す
- **runner-agent**: Docker SDK 経由で Minecraft コンテナを操作する独立サービス。API Core / Worker とは別にデプロイ可能
- **postgres**: 全サービス共通のデータストア。jobs テーブルがジョブキューを兼ねる (MVP)
- **redis**: WebSocket pub/sub チャネル (api 複数レプリカ時のログ/ステータス配信)

## 2. 方針の要点

### 2.1 実行基盤の分離 (Issues §2, §4 への解)
- API Core は **Minecraft プロセスを直接 fork しない**
- Runner は差し替え可能なドライバ (Docker / Podman / Kubernetes / リモートホスト over SSH)
- Runner プロファイルで Java バージョン/メモリ/追加パッケージを宣言

### 2.2 Organization 基盤 (Issues §1, §5 への解)
- 全ドメインモデルに `organization_id` を必須化 (Tenant/Workspace の 2 層構造は採用しない)
- 認可は **機能別パーミッション** を一次、Role テンプレートを二次として設計
- 行レベル (Row-Level) の参照制御をクエリ/リポジトリ層で強制

### 2.3 非同期実行 (Issues §3 への解)
- 起動・停止・バックアップは Job として永続化し、ワーカーが Runner に指示
- ポート/リソース競合は Runner 層 (Docker/K8s) のネットワーク/スケジューラに委譲
- API Core はリソース割り当てを直接やらない

### 2.4 ステートレス API Core (NFR-SC-1, NFR-RL-1)
- 状態は DB/キュー/Runner 側にのみ持つ
- API Core 再起動で Minecraft サーバーが巻き込まれない

## 3. データモデル方針 (概略)

```
Organization ─┬─ Server ──── Job (start/stop/delete/restore...)
              │         └─── Backup
              ├─ Group ────── GroupPlayer
              ├─ Member (User×Organization) ── custom_permissions
              └─ AuditLog

Server ─── ServerGroup (attach) ─── Group
```

- `Organization` がリソース分離の主軸 (Tenant/Workspace の 2 層は採用しない)
- `OrganizationMember.role_template` で owner/admin/operator/viewer を管理、`custom_permissions` で個別上書き
- `Server.runner_type` と `runner_instance_id` で Runner 上の実行インスタンスを追跡
- `Backup`/`FileEditHistory` は `storage_backend + storage_key` でストレージ抽象化

## 4. 技術選定 (確定)

| レイヤ | 採用 | 備考 |
|--------|------|------|
| 言語 | **Go** | - |
| API フレームワーク | **Echo** | WebSocket・ミドルウェアが充実 |
| DB | **PostgreSQL** | SQLite はマルチインスタンス化に不向き |
| DB ドライバ | **pgx/v5** | - |
| クエリ生成 | **sqlc** | SQL から型安全な Go コードを生成 |
| マイグレーション | **goose** | - |
| Job Queue (MVP) | **PostgreSQL テーブル** | `SELECT FOR UPDATE SKIP LOCKED` でワーカー競合を防ぐ |
| Job Queue (Phase 2) | Redis / NATS JetStream | 専用キューへの移行を検討 |
| WebSocket pub/sub | **Redis** | api 複数レプリカ時のログ/ステータス配信 |
| Runner (MVP) | **Docker Engine API** | docker/docker 公式 Go SDK |
| Runner (Phase 2) | Kubernetes | StatefulSet or Custom Operator |
| Runner 認証 (MVP) | **Bearer Token (共有シークレット)** | Worker → Runner Agent 間。同一 Docker ネットワーク内 |
| 監視 | OpenTelemetry + Prometheus | |
| リポジトリ構成 | **モノレポ** | cmd/api, cmd/worker, cmd/runner-agent を 1 Go モジュールで管理 |
| ローカル開発 | **Docker Compose** | 全コンテナを一括起動 |

## 5. 主要リスクと対応方針

- **R-1** Worker → Runner Agent 間通信のネットワーク断時のジョブ状態整合
  - Worker 起動時に `status=running` のまま完了していないジョブを検出して再実行 (at-least-once)
- **R-2** コンテナ化時の永続ストレージ (ワールドデータ/バックアップ) の扱い
  - Docker volume または bind mount。Runner Agent がパスを管理
- **R-3** ~~RCON 接続を API Core から直接張るか、Runner Agent 経由にするか~~ → **決定済み: Runner Agent 経由**
- **R-4** Organization 横断のオペレーション (複数 Organization をまたいで保守する場面) の権限モデル
  - MVP では対象外。将来的にスーパー管理者ロールで対応
- **R-5** ~~v1 データの移行可否~~ → **決定済み: MVP では移行しない** (要件 §5 C-2)

## 6. 次ステップ

1. モノレポのディレクトリ骨格と `go.mod` の作成 (`docs/05-monorepo-structure.md` 参照)
2. Docker Compose の整備 (postgres / redis / api / worker / runner-agent)
3. goose マイグレーションファイルの作成 (全テーブル定義)
4. sqlc 設定とクエリ定義
5. `cmd/api` — 認証エンドポイントから実装開始
