# 機能一覧 (v1 現行実装より抽出)

v2 設計の入力として、v1 の全エンドポイントと機能を整理したものです。
各エンドポイントの詳細仕様は `specs/` 配下を参照してください。

## サマリー

| ドメイン | v1 エンドポイント数 | v2 仕様 |
|----------|-----------------|---------|
| 認証 (Auth) | 3 | [specs/01-auth-users.md](specs/01-auth-users.md) |
| ユーザー管理 (Users) | 9 | [specs/01-auth-users.md](specs/01-auth-users.md) |
| グループ管理 (Groups) | 11 | [specs/02-groups.md](specs/02-groups.md) |
| サーバー管理 (Server Management) | 5 | [specs/03-servers.md](specs/03-servers.md) |
| サーバー制御 (Server Control) | 6 | [specs/03-servers.md](specs/03-servers.md) |
| サーバーユーティリティ | 6 | [specs/03-servers.md](specs/03-servers.md) ※v2 では Runner 抽象化により大半廃止 |
| インポート/エクスポート | 2 | v2 廃止 |
| バージョン管理 (Versions) | 6 | [specs/04-versions.md](specs/04-versions.md) |
| バックアップ (Backups) | 11 | [specs/05-backups.md](specs/05-backups.md) |
| バックアップスケジューラー | 7 | [specs/05-backups.md](specs/05-backups.md) |
| テンプレート (Templates) | 8 | **v2 廃止** (バックアップ復元で代替) |
| ファイル管理 (Files) | 9 | [specs/07-files.md](specs/07-files.md) |
| ファイル編集履歴 | 5 | [specs/07-files.md](specs/07-files.md) |
| リアルタイム通信 (WebSocket) | 3 | [specs/08-realtime.md](specs/08-realtime.md) ※v2 で /logs と /status を /console に統合 |
| 監査ログ (Audit) | 4 | [specs/09-audit.md](specs/09-audit.md) |
| 可視性制御 (Visibility) | 6 | **v2 廃止** (Organization メンバーシップで代替) |
| **合計** | **101** | - |

---

## 1. 認証 (Auth)

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | POST | `/api/v1/auth/token` | 不要 | ログイン (username + password → JWT + refresh token) |
| 2 | POST | `/api/v1/auth/refresh` | 不要 | アクセストークン更新 (refresh token → 新 JWT) |
| 3 | POST | `/api/v1/auth/logout` | 不要 | ログアウト (refresh token 失効) |

---

## 2. ユーザー管理 (Users)

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | POST | `/api/v1/users/register` | 不要 | ユーザー登録 (初回登録者は自動で admin) |
| 2 | GET | `/api/v1/users/me` | User | 自分のプロフィール取得 |
| 3 | PUT | `/api/v1/users/me` | User | 自分のユーザー名/メール更新 |
| 4 | PUT | `/api/v1/users/me/password` | User | 自分のパスワード変更 |
| 5 | DELETE | `/api/v1/users/me` | User | 自分のアカウント削除 (パスワード確認要) |
| 6 | GET | `/api/v1/users/` | Admin | 全ユーザー一覧取得 |
| 7 | POST | `/api/v1/users/approve/{user_id}` | Admin | ユーザー承認 |
| 8 | PUT | `/api/v1/users/role/{user_id}` | Admin | ユーザーロール変更 |
| 9 | DELETE | `/api/v1/users/{user_id}` | Admin | 管理者によるユーザー削除 |

---

## 3. グループ管理 (Groups)

プレイヤーグループ (OP リスト / ホワイトリスト) の CRUD と、サーバーへの attach/detach。

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | POST | `/api/v1/groups` | User | グループ作成 |
| 2 | GET | `/api/v1/groups` | User | グループ一覧取得 |
| 3 | GET | `/api/v1/groups/{group_id}` | User | グループ詳細取得 |
| 4 | PUT | `/api/v1/groups/{group_id}` | User | グループ更新 |
| 5 | DELETE | `/api/v1/groups/{group_id}` | User | グループ削除 (attach 中は不可) |
| 6 | POST | `/api/v1/groups/{group_id}/players` | User | プレイヤー追加 (UUID or ユーザー名、Mojang API で解決) |
| 7 | DELETE | `/api/v1/groups/{group_id}/players/{uuid}` | User | プレイヤー削除 |
| 8 | POST | `/api/v1/groups/{group_id}/servers` | ServerOwner/Admin | グループをサーバーに attach |
| 9 | DELETE | `/api/v1/groups/{group_id}/servers/{server_id}` | ServerOwner/Admin | グループをサーバーから detach |
| 10 | GET | `/api/v1/groups/{group_id}/servers` | User | グループが attach されているサーバー一覧 |
| 11 | GET | `/api/v1/groups/servers/{server_id}` | User | サーバーに attach されているグループ一覧 |

---

## 4. サーバー管理 (Server Management)

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | POST | `/api/v1/servers` | User | サーバー作成 (JAR DL、ディレクトリ生成含む) |
| 2 | GET | `/api/v1/servers` | User | サーバー一覧取得 (ページネーション) |
| 3 | GET | `/api/v1/servers/{server_id}` | User | サーバー詳細取得 |
| 4 | PUT | `/api/v1/servers/{server_id}` | User | サーバー更新 (停止中のみ一部変更可) |
| 5 | DELETE | `/api/v1/servers/{server_id}` | Owner/Admin | サーバー削除 (論理削除) |

---

## 5. サーバー制御 (Server Control)

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | POST | `/api/v1/servers/{server_id}/start` | User | サーバー起動 (daemon プロセス作成) |
| 2 | POST | `/api/v1/servers/{server_id}/stop` | User | サーバー停止 (`?force=false`) |
| 3 | POST | `/api/v1/servers/{server_id}/restart` | User | サーバー再起動 |
| 4 | GET | `/api/v1/servers/{server_id}/status` | User | サーバー状態取得 |
| 5 | POST | `/api/v1/servers/{server_id}/command` | User | コンソールコマンド送信 (RCON/stdin) |
| 6 | GET | `/api/v1/servers/{server_id}/logs` | User | ログ取得 (`?lines=100`) |

---

## 6. サーバーユーティリティ

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | GET | `/api/v1/servers/versions/supported` | 不要 | サポートバージョン一覧 |
| 2 | POST | `/api/v1/servers/sync` | Admin | DB とプロセス状態の同期 |
| 3 | GET | `/api/v1/servers/cache/stats` | Admin | JAR キャッシュ統計 |
| 4 | POST | `/api/v1/servers/cache/cleanup` | Admin | JAR キャッシュクリーンアップ |
| 5 | GET | `/api/v1/servers/java/compatibility` | 不要 | Java インストール情報一覧 |
| 6 | GET | `/api/v1/servers/java/validate/{mc_version}` | 不要 | 指定 MC バージョンの Java 互換確認 |

---

## 7. インポート/エクスポート

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | GET | `/api/v1/servers/{server_id}/export` | User | サーバーを ZIP でエクスポート |
| 2 | POST | `/api/v1/servers/import` | Operator/Admin | ZIP からサーバーをインポート (最大 500MB) |

---

## 8. バージョン管理 (Versions)

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | GET | `/api/versions/supported` | 不要 | DB からサポートバージョン一覧 |
| 2 | POST | `/api/versions/update` | Admin | バージョン情報を外部 API から手動更新 |
| 3 | GET | `/api/versions/scheduler/status` | Admin | バージョン更新スケジューラー状態 |
| 4 | GET | `/api/versions/stats` | 不要 | バージョン統計情報 |
| 5 | GET | `/api/versions/{server_type}` | 不要 | 特定サーバータイプのバージョン一覧 |
| 6 | GET | `/api/versions/{server_type}/{version}` | 不要 | 特定バージョン詳細 |

---

## 9. バックアップ (Backups)

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | POST | `/servers/{server_id}/backups` | User | バックアップ作成 |
| 2 | POST | `/servers/{server_id}/backups/upload` | User | バックアップ tar.gz アップロード (最大 500MB) |
| 3 | GET | `/servers/{server_id}/backups` | User | サーバーバックアップ一覧 |
| 4 | GET | `/backups` | Admin | 全バックアップ一覧 |
| 5 | GET | `/backups/statistics` | Admin | バックアップ統計 (全体) |
| 6 | GET | `/servers/{server_id}/backups/statistics` | User | バックアップ統計 (サーバー単位) |
| 7 | GET | `/backups/{backup_id}` | User | バックアップ詳細 |
| 8 | POST | `/backups/{backup_id}/restore` | User | バックアップ復元 |
| 9 | POST | `/backups/{backup_id}/restore-with-template` | User | バックアップ復元 + テンプレート生成 **(v2 廃止)** |
| 10 | GET | `/backups/{backup_id}/download` | User | バックアップファイルダウンロード |
| 11 | DELETE | `/backups/{backup_id}` | Owner/Admin | バックアップ削除 |

### バックアップスケジューラー

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | POST | `/scheduler/servers/{server_id}/schedule` | User | スケジュール作成 |
| 2 | GET | `/scheduler/servers/{server_id}/schedule` | User | スケジュール取得 |
| 3 | PUT | `/scheduler/servers/{server_id}/schedule` | User | スケジュール更新 |
| 4 | DELETE | `/scheduler/servers/{server_id}/schedule` | User | スケジュール削除 |
| 5 | GET | `/scheduler/servers/{server_id}/logs` | User | スケジュール実行ログ |
| 6 | GET | `/scheduler/status` | Admin | スケジューラー全体状態 |
| 7 | GET | `/scheduler/schedules` | Admin | 全スケジュール一覧 |

---

## 10. テンプレート (Templates)

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | POST | `/from-server/{server_id}` | Operator/Admin | サーバーからテンプレート作成 |
| 2 | POST | `/` | Operator/Admin | カスタムテンプレート作成 |
| 3 | GET | `/` | User | テンプレート一覧 (非 admin は public or 自分のもの) |
| 4 | GET | `/{template_id}` | User | テンプレート詳細 |
| 5 | PUT | `/{template_id}` | Creator/Admin | テンプレート更新 |
| 6 | DELETE | `/{template_id}` | Creator/Admin | テンプレート削除 (使用中は不可) |
| 7 | GET | `/statistics` | User | テンプレート統計 |
| 8 | POST | `/{template_id}/clone` | Operator/Admin | テンプレート複製 |

---

## 11. ファイル管理 (Files)

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | GET | `/servers/{server_id}/files/{path}` | User | ファイル/ディレクトリ一覧 |
| 2 | GET | `/servers/{server_id}/files/{path}/read` | User | ファイル内容読み取り (エンコード自動検出) |
| 3 | GET | `/servers/{server_id}/files/{path}/download` | User | ファイルダウンロード |
| 4 | POST | `/servers/{server_id}/files/upload` | User | ファイルアップロード (アーカイブ展開オプション付き) |
| 5 | PUT | `/servers/{server_id}/files/{path}` | User | ファイル書き込み (バックアップ作成オプション付き) |
| 6 | DELETE | `/servers/{server_id}/files/{path}` | User | ファイル/ディレクトリ削除 |
| 7 | PATCH | `/servers/{server_id}/files/{path}/rename` | User | ファイル/ディレクトリリネーム |
| 8 | POST | `/servers/{server_id}/files/{path}/directories` | User | ディレクトリ作成 |
| 9 | POST | `/servers/{server_id}/files/search` | User | ファイル検索 (ファイル名/内容) |

### ファイル編集履歴

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | GET | `/servers/{server_id}/files/{path}/history` | User | ファイル編集履歴一覧 |
| 2 | GET | `/servers/{server_id}/files/{path}/history/{version}` | User | 特定バージョンの内容取得 |
| 3 | POST | `/servers/{server_id}/files/{path}/history/{version}/restore` | User | バージョンから復元 |
| 4 | DELETE | `/servers/{server_id}/files/{path}/history/{version}` | Admin | バージョン削除 |
| 5 | GET | `/servers/{server_id}/files/history/statistics` | User | ファイル履歴統計 |

---

## 12. リアルタイム通信 (WebSocket)

| # | Protocol | Path | 認証 | 概要 |
|---|----------|------|------|------|
| 1 | WS | `/servers/{server_id}/logs` | token クエリパラメータ | サーバーログ/コマンドのリアルタイム配信 |
| 2 | WS | `/servers/{server_id}/status` | token クエリパラメータ | サーバー状態のリアルタイム配信 |
| 3 | WS | `/notifications` | token クエリパラメータ | システム通知ストリーム |

---

## 13. 監査ログ (Audit)

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | GET | `/api/v1/audit/logs` | User | 監査ログ一覧 (非 admin は自分のみ) |
| 2 | GET | `/api/v1/audit/security-alerts` | Admin | セキュリティアラート一覧 |
| 3 | GET | `/api/v1/audit/user/{user_id}/activity` | User/Admin | ユーザーアクティビティ |
| 4 | GET | `/api/v1/audit/statistics` | Admin | 監査統計情報 |

---

## 14. 可視性制御 (Visibility) — Phase 2

| # | Method | Path | 認証 | 概要 |
|---|--------|------|------|------|
| 1 | GET | `/visibility/{resource_type}/{resource_id}` | Owner/Admin | リソース可視性設定取得 |
| 2 | PUT | `/visibility/{resource_type}/{resource_id}` | Owner/Admin | 可視性設定更新 |
| 3 | POST | `/visibility/{resource_type}/{resource_id}/grant-access` | Owner/Admin | 特定ユーザーへのアクセス付与 |
| 4 | DELETE | `/visibility/{resource_type}/{resource_id}/revoke-access/{user_id}` | Owner/Admin | 特定ユーザーのアクセス取り消し |
| 5 | GET | `/visibility/migration/status` | Admin | 移行状況確認 |
| 6 | POST | `/visibility/migration/execute` | Admin | 移行実行 |

---

## データモデル一覧 (v2)

v1 からの変更を反映した v2 のデータモデル。

| モデル | テーブル | 詳細仕様 |
|--------|----------|---------|
| User | users | [specs/01-auth-users.md](specs/01-auth-users.md) |
| RefreshToken | refresh_tokens | [specs/01-auth-users.md](specs/01-auth-users.md) |
| Organization | organizations | [specs/01-auth-users.md](specs/01-auth-users.md) |
| OrganizationMember | organization_members | [specs/01-auth-users.md](specs/01-auth-users.md) |
| OrganizationInvitation | organization_invitations | [specs/01-auth-users.md](specs/01-auth-users.md) *(Phase 2)* |
| PersonalAccessToken | personal_access_tokens | [specs/01-auth-users.md](specs/01-auth-users.md) *(Phase 2)* |
| Group | groups | [specs/02-groups.md](specs/02-groups.md) |
| GroupPlayer | group_players | [specs/02-groups.md](specs/02-groups.md) |
| ServerGroup (attachment) | server_groups | [specs/02-groups.md](specs/02-groups.md) |
| Server | servers | [specs/03-servers.md](specs/03-servers.md) |
| MinecraftVersion | minecraft_versions | [specs/04-versions.md](specs/04-versions.md) |
| VersionUpdateLog | version_update_logs | [specs/04-versions.md](specs/04-versions.md) |
| Backup | backups | [specs/05-backups.md](specs/05-backups.md) |
| BackupSchedule | backup_schedules | [specs/05-backups.md](specs/05-backups.md) |
| BackupScheduleLog | backup_schedule_logs | [specs/05-backups.md](specs/05-backups.md) |
| FileEditHistory | file_edit_history | [specs/07-files.md](specs/07-files.md) |
| AuditLog | audit_logs | [specs/09-audit.md](specs/09-audit.md) |
