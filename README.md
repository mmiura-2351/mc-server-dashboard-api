# Minecraft Server Dashboard API — v2 設計ドキュメント

このリポジトリの `redesign/v2-requirements` ブランチは、Minecraft Server Dashboard API の v2 再設計に向けた **要件定義・仕様書専用ブランチ** です。実装コードは含みません。

## 背景

v1 は設計フェーズを省略して機能追加を繰り返した結果、以下の領域で後から変更が困難な破綻が生じています。

- Organization 単位のアクセス制御・権限管理
- API プロセスと Minecraft サーバープロセスの実行環境分離
- 複数サーバーの同時実行
- 実行基盤の抽象化（v1 は host 上で直接 `fork(2)` + Java 起動）

これらはモジュール単位の置き換えでは解決できないため、要件から再整理して v2 として作り直します。

## ドキュメント構成

```
docs/redesign/
├── 01-current-issues.md          # v1 の設計破綻の詳細分析
├── 02-requirements.md            # v2 機能/非機能要件 (FR-*, NFR-*)
├── 03-architecture-direction.md  # アーキテクチャ方針
├── 04-feature-list.md            # v1 機能一覧と v2 での扱い
└── specs/
    ├── 01-auth-users.md          # 認証 / Organization / ユーザー管理
    ├── 02-groups.md              # プレイヤーグループ (OP/whitelist)
    ├── 03-servers.md             # サーバー管理・制御
    ├── 04-versions.md            # Minecraft バージョン管理
    ├── 05-backups.md             # バックアップ / スケジューラー
    ├── 06-jobs.md                # 非同期ジョブ共通仕様
    ├── 07-files.md               # ファイル管理・編集履歴
    ├── 08-realtime.md            # リアルタイム通信 (WebSocket)
    └── 09-audit.md               # 監査ログ
```

## 主要な設計方針

| 項目 | 決定内容 |
|------|---------|
| リソース分離単位 | Organization (1 層)。Tenant/Workspace の 2 層構造は採用しない |
| Runner 抽象化 | API Core はファイルシステムに直接触れない。すべての操作を Runner インターフェース経由にする (Docker/Podman が MVP ターゲット) |
| 非同期ジョブ | サーバー起動/停止/作成/削除・バックアップ操作はすべて `202 + job_id` を返す |
| 設定の責務分離 | DB はインフラ設定のみ。`server.properties` 等ゲーム設定はファイルが唯一の真実の源 |
| API 互換 | 既存フロントエンド (`mc-server-dashboard-ui`) との互換は **維持しない** |
| テンプレート機能 | **v2 廃止**。バックアップ復元で代替する |
| 多言語対応 | **対象外** |

## ブランチの位置付け

- このブランチ (`redesign/v2-requirements`) は要件定義・仕様書のみを含む
- v2 実装は別リポジトリまたは `v2/` ディレクトリ配下で進める予定
- v1 実装は `master` ブランチで保守モードを継続

## 未決定事項

- v2 を同リポジトリ内に共存させるか、新規リポジトリとして切り出すか
- v1 からの移行経路（データ/サーバーディレクトリ）の要否
- ジョブキューの実装選定（Redis / Postgres-based / NATS 等）
- DB を SQLite のまま MVP にするか、最初から PostgreSQL を前提にするか

## License

MIT License — see [LICENSE](LICENSE) for details.
