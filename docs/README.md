# v2 設計ドキュメント

Minecraft Server Dashboard API v2 の要件定義・仕様書をまとめたディレクトリです。

## なぜ v2 を作り直すか

v1 は設計フェーズを省略して機能追加を繰り返した結果、以下の領域でモジュール単位の置き換えでは解決できない破綻が生じました。

- Organization 単位のアクセス制御・権限管理
- API プロセスと Minecraft サーバープロセスの実行環境分離
- 複数サーバーの同時実行
- 実行基盤の抽象化（v1 は host 上で直接 `fork(2)` + Java 起動）

詳細は `01-current-issues.md` を参照してください。

## ドキュメント一覧

| ファイル | 内容 |
|----------|------|
| `01-current-issues.md` | v1 の設計破綻の詳細分析 |
| `02-requirements.md` | v2 の機能/非機能要件 (FR-*, NFR-*) — オープン事項すべて解決済み |
| `03-architecture-direction.md` | アーキテクチャ方針・技術スタック (確定) |
| `04-feature-list.md` | v1 機能一覧と v2 での扱い (廃止・変更・継続) |
| `05-monorepo-structure.md` | モノレポ構成・Docker Compose・サービス間通信仕様 |
| `specs/01-auth-users.md` | 認証 / Organization / ユーザー管理 |
| `specs/02-groups.md` | プレイヤーグループ (Minecraft OP/whitelist) |
| `specs/03-servers.md` | サーバー管理・制御 |
| `specs/04-versions.md` | Minecraft バージョン管理 |
| `specs/05-backups.md` | バックアップ管理 / スケジューラー |
| `specs/06-jobs.md` | 非同期ジョブ共通仕様 |
| `specs/07-files.md` | ファイル管理 / 編集履歴 |
| `specs/08-realtime.md` | リアルタイム通信 (WebSocket) |
| `specs/09-audit.md` | 監査ログ |

## 確定した設計方針

議論を経て確定済みの事項。仕様書を書く際はこれらに反しないこと。

- **リソース分離単位**: Organization (1 層)。Tenant/Workspace の 2 層構造は採用しない
- **非同期ジョブ**: サーバー起動/停止/作成/削除・バックアップ操作はすべて `202 + job_id` を返す
- **Runner 抽象化**: API Core はファイルシステムに直接触れない。Runner インターフェース経由のみ
- **設定の責務分離**: DB はインフラ設定のみ。`server.properties` 等はファイルが唯一の真実の源
- **テンプレート機能**: v2 廃止。バックアップ復元で代替する
- **既存 API との互換**: 維持しない。v2 は新規 API 契約で設計する
