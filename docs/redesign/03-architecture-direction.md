# v2 アーキテクチャ方針 (叩き台)

`02-requirements.md` の要件を満たすためのアーキテクチャの **方向性** を示します。
設計レビューで合意するまでは暫定であり、本ドキュメント単体で実装を開始しないこと。

## 1. 全体構成 (論理)

```
        ┌────────────────────┐
        │  Web UI / CLI /    │
        │  External API User │
        └─────────┬──────────┘
                  │ (HTTPS, JWT/PAT)
        ┌─────────▼──────────┐
        │     API Core       │  ← ステートレス / 水平スケール
        │ (FastAPI or other) │
        └──┬──────┬──────┬───┘
           │      │      │
       RDB │      │ Queue│  WebSocket/SSE
           │      │      │
     ┌─────▼┐  ┌──▼────┐ │
     │ RDB  │  │Job    │ │
     │(PG)  │  │Queue  │ │
     └──────┘  └──┬────┘ │
                  │      │
        ┌─────────▼──────▼───────┐
        │     Runner Agent       │ ← ホスト毎 / クラスタ毎
        │ (Docker / K8s driver)  │
        └─────────┬──────────────┘
                  │ (exec / attach / logs)
        ┌─────────▼──────────────┐
        │ Minecraft Server       │ ← コンテナ/Pod
        │ (JVM process in sandbox)│
        └────────────────────────┘
```

- **API Core**: HTTP/WebSocket エンドポイント、認可、データ永続化の入出力
- **Job Queue**: 起動/停止/バックアップ等の非同期ジョブを保持
- **Runner Agent**: Runner (Docker/K8s 等) に対する操作をラップする常駐プロセス
- **Runner**: Minecraft サーバープロセスをサンドボックス内で実行する基盤

## 2. 方針の要点

### 2.1 実行基盤の分離 (Issues §2, §4 への解)
- API Core は **Minecraft プロセスを直接 fork しない**
- Runner は差し替え可能なドライバ (Docker / Podman / Kubernetes / リモートホスト over SSH)
- Runner プロファイルで Java バージョン/メモリ/追加パッケージを宣言

### 2.2 マルチテナント基盤 (Issues §1, §5 への解)
- 全ドメインモデルに `tenant_id` と `workspace_id` を必須化
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
Tenant ─┬─ Workspace ─┬─ Server ─── ServerRevision
        │             ├─ Group
        │             └─ Template
        ├─ Member (User×Tenant) ── MemberPermission
        └─ ApiToken

Server ─┬─ Job (backup/start/stop/restore...)
        ├─ Backup
        └─ AuditLog
```

- `Server.runner_profile_id` で Runner プロファイル参照
- `Server.current_runtime` は Runner Agent の割り当て (Pod ID / container ID 等)
- `MemberPermission` は `(member_id, scope, action)` 構造で拡張性を確保

## 4. 技術選定 (候補)

| レイヤ | 候補 | 備考 |
|--------|------|------|
| API Core | FastAPI / Litestar | Python 継続なら FastAPI |
| DB | PostgreSQL | SQLite はテナント化と同時スケールに不向き |
| Queue | Redis + RQ / Arq / Dramatiq / NATS JetStream | 永続性と運用容易性で選定 |
| Runner (MVP) | Docker Engine API | 単一ホスト前提 |
| Runner (Phase 2) | Kubernetes | StatefulSet or Custom Operator |
| 監視 | OpenTelemetry + Prometheus | |
| 認可 | Casbin / 自前ポリシーエンジン | ABAC 相当が必要なら Casbin |

## 5. 主要リスクと先行検討事項

- **R-1** Runner Agent ↔ API Core 間通信の信頼性 (ネットワーク断時のジョブ状態整合)
- **R-2** コンテナ化時の永続ストレージ (ワールドデータ/バックアップ) の扱い
- **R-3** RCON 接続を API Core から直接張るか、Runner Agent 経由にするか
- **R-4** テナント跨ぎのオペレーション (運営が全テナントをまたいで保守する場面) の権限モデル
- **R-5** v1 データの移行可否 (要件 §5 C-2 とのすり合わせ)

## 6. 次ステップ

1. 本ドキュメント + 要件を **レビュー**、オープン事項 (要件 §7) を決定
2. R-1〜R-5 のスパイク実装 (PoC) をタスク化
3. データモデルと API 契約 (OpenAPI) のドラフト作成
4. MVP スコープの合意と v2 リポジトリ/ディレクトリ方針の決定
