# プロジェクト再設計ドキュメント

このディレクトリは、現行 Minecraft Server Dashboard API の設計上の破綻を整理し、
新バージョン (v2) を設計し直すためのドキュメント群です。

## 背景

現行実装 (v1) は設計フェーズを省略して機能追加を繰り返した結果、
以下の「後から変更が難しい層」で破綻が発生しています。

- ユーザー/Organization 単位の機能制限・権限管理
- アプリケーションと Minecraft サーバープロセスの実行環境の分離
- 複数サーバーの同時実行
- 実行環境の抽象化 (現状 host 上で直接 `fork(2)` + Java 起動)
- Organization 単位でのサーバー分離

これらはモジュール単位の置き換えでは解決できないため、
要件から再整理した上で v2 として作り直します。

## ドキュメント構成

| ファイル | 役割 |
|----------|------|
| `01-current-issues.md` | v1 の設計上の破綻の詳細分析 |
| `02-requirements.md` | v2 の機能/非機能要件 |
| `03-architecture-direction.md` | v2 のアーキテクチャ方針 (叩き台) |
| `04-feature-list.md` | v1 機能一覧と v2 での扱い (廃止・変更・継続) |
| `specs/01-auth-users.md` | 認証 / Organization / ユーザー管理 |
| `specs/02-groups.md` | プレイヤーグループ管理 |
| `specs/03-servers.md` | サーバー管理・制御 |
| `specs/04-versions.md` | Minecraft バージョン管理 |
| `specs/05-backups.md` | バックアップ管理 / スケジューラー |
| `specs/07-files.md` | ファイル管理 / 編集履歴 |
| `specs/08-realtime.md` | リアルタイム通信 (WebSocket) |
| `specs/09-audit.md` | 監査ログ |

## 位置付け

このブランチ (`redesign/v2-requirements`) は **要件定義のみ** を含みます。
実装は行わず、レビューと合意の後に以下を分岐させます。

- v2 実装は別リポジトリまたは `v2/` ディレクトリ配下で進める
- v1 (master) は当面の運用のため保守モードで維持

## 決定待ち事項

- v2 を同リポジトリ内に共存させるか、新規リポジトリとして切り出すか
- v1 からの移行経路 (データ/サーバーディレクトリ) の要否
- 既存フロントエンド (`mc-server-dashboard-ui`) との互換 API を維持するか
