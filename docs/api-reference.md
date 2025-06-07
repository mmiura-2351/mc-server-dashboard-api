# API Reference - Minecraft Server Dashboard

本ドキュメントは、Minecraft Server Dashboard APIの完全なリファレンスです。

## ベースURL

すべてのAPIエンドポイントは `/api/v1/` プレフィックスを使用します。

## 認証

JWT Bearerトークンによる認証が必要です（公開エンドポイント除く）：
```
Authorization: Bearer <token>
```

## 🔐 認証システム

### ユーザー認証
- **POST** `/api/v1/users/register` - ユーザー登録
  - Body: `{username, email, password, full_name}`
  - Response: `UserResponse`
  - 権限: 公開

- **POST** `/api/v1/auth/token` - ログイン（OAuth2形式）
  - Body: `username=<username>&password=<password>`
  - Response: `{access_token, token_type}`
  - 権限: 公開

- **GET** `/api/v1/users/me` - 現在のユーザー情報取得
  - Response: `UserResponse`
  - 権限: 認証済み

## 👥 ユーザー管理

### ユーザー操作
- **GET** `/api/v1/users/` - ユーザー一覧
  - Response: `UserListResponse`
  - 権限: admin

- **POST** `/api/v1/users/approve/{user_id}` - ユーザー承認
  - Response: `UserResponse`
  - 権限: admin

- **PUT** `/api/v1/users/role/{user_id}` - ユーザーロール変更
  - Body: `{role: "user"|"operator"|"admin"}`
  - Response: `UserResponse`
  - 権限: admin

- **PUT** `/api/v1/users/me` - プロファイル更新
  - Body: `{username?, email?}`
  - Response: `UserResponse + access_token`
  - 権限: 認証済み

- **PUT** `/api/v1/users/me/password` - パスワード変更
  - Body: `{current_password, new_password}`
  - Response: `UserResponse + access_token`
  - 権限: 認証済み

- **DELETE** `/api/v1/users/{user_id}` - ユーザー削除
  - Response: `{message}`
  - 権限: admin

## 🖥️ サーバー管理

### サーバーCRUD操作
- **POST** `/api/v1/servers` - サーバー作成
  - Body: `ServerCreateRequest`
  - Response: `ServerResponse`
  - 権限: operator, admin

- **GET** `/api/v1/servers` - サーバー一覧
  - Query: `page`, `size`
  - Response: `ServerListResponse`
  - 権限: 全ユーザー（所有者フィルタ適用）

- **GET** `/api/v1/servers/{server_id}` - サーバー詳細
  - Response: `ServerResponse`
  - 権限: 所有者, admin

- **PUT** `/api/v1/servers/{server_id}` - サーバー更新
  - Body: `ServerUpdateRequest`
  - Response: `ServerResponse`
  - 権限: 所有者, admin

- **DELETE** `/api/v1/servers/{server_id}` - サーバー削除（ソフトデリート）
  - 権限: 所有者, admin

### サーバープロセス制御
- **POST** `/api/v1/servers/{server_id}/start` - サーバー開始
  - Response: `ServerStatusResponse`
  - 権限: 所有者, admin

- **POST** `/api/v1/servers/{server_id}/stop` - サーバー停止
  - Query: `force` (boolean)
  - 権限: 所有者, admin

- **POST** `/api/v1/servers/{server_id}/restart` - サーバー再起動
  - 権限: 所有者, admin

- **GET** `/api/v1/servers/{server_id}/status` - サーバー状態取得
  - Response: `ServerStatusResponse`
  - 権限: 所有者, admin

- **POST** `/api/v1/servers/{server_id}/command` - コンソールコマンド送信
  - Body: `ServerCommandRequest`
  - 権限: 所有者, admin

- **GET** `/api/v1/servers/{server_id}/logs` - サーバーログ取得
  - Query: `lines` (1-1000)
  - Response: `ServerLogsResponse`
  - 権限: 所有者, admin

### ユーティリティ
- **GET** `/api/v1/servers/versions/supported` - サポート対象Minecraftバージョン一覧
  - Response: `SupportedVersionsResponse`
  - 権限: 認証済み

- **POST** `/api/v1/servers/sync` - サーバー状態同期（管理者専用）
  - 権限: admin

## 👫 グループ管理

### グループ操作
- **POST** `/api/v1/groups` - グループ作成
  - Body: `GroupCreateRequest`
  - Response: `GroupResponse`
  - 権限: operator, admin

- **GET** `/api/v1/groups` - グループ一覧
  - Query: `group_type` (op/whitelist)
  - Response: `GroupListResponse`
  - 権限: 全ユーザー（所有者フィルタ適用）

- **GET** `/api/v1/groups/{group_id}` - グループ詳細
  - Response: `GroupResponse`
  - 権限: 所有者, admin

- **PUT** `/api/v1/groups/{group_id}` - グループ更新
  - Body: `GroupUpdateRequest`
  - Response: `GroupResponse`
  - 権限: 所有者, admin

- **DELETE** `/api/v1/groups/{group_id}` - グループ削除
  - 権限: 所有者, admin

### プレイヤー管理
- **POST** `/api/v1/groups/{group_id}/players` - プレイヤー追加
  - Body: `PlayerAddRequest`
  - Response: `GroupResponse`
  - 権限: 所有者, admin

- **DELETE** `/api/v1/groups/{group_id}/players/{player_uuid}` - プレイヤー削除
  - Response: `GroupResponse`
  - 権限: 所有者, admin

### サーバー連携
- **POST** `/api/v1/groups/{group_id}/servers` - サーバーへのグループ適用
  - Body: `ServerAttachRequest`
  - 権限: 所有者, admin

- **DELETE** `/api/v1/groups/{group_id}/servers/{server_id}` - グループのサーバー分離
  - 権限: 所有者, admin

- **GET** `/api/v1/groups/{group_id}/servers` - グループ適用サーバー一覧
  - Response: `GroupServersResponse`
  - 権限: 所有者, admin

- **GET** `/api/v1/groups/servers/{server_id}` - サーバー適用グループ一覧
  - Response: `ServerGroupsResponse`
  - 権限: 所有者, admin

## 💾 バックアップ管理

### バックアップ操作
- **POST** `/api/v1/backups/servers/{server_id}/backups` - バックアップ作成
  - Body: `BackupCreateRequest`
  - Response: `BackupResponse`
  - 権限: operator, admin

- **GET** `/api/v1/backups/servers/{server_id}/backups` - サーバーバックアップ一覧
  - Query: `page`, `size`, `backup_type`
  - Response: `BackupListResponse`
  - 権限: 所有者, admin

- **GET** `/api/v1/backups/backups` - 全バックアップ一覧（管理者専用）
  - Query: `page`, `size`, `backup_type`
  - Response: `BackupListResponse`
  - 権限: admin

- **GET** `/api/v1/backups/backups/{backup_id}` - バックアップ詳細
  - Response: `BackupResponse`
  - 権限: 所有者, admin

- **POST** `/api/v1/backups/backups/{backup_id}/restore` - バックアップ復元
  - Body: `BackupRestoreRequest`
  - Response: `BackupOperationResponse`
  - 権限: operator, admin

- **POST** `/api/v1/backups/backups/{backup_id}/restore-with-template` - バックアップ復元＋テンプレート作成
  - Body: `BackupRestoreWithTemplateRequest`
  - Response: `BackupRestoreWithTemplateResponse`
  - 権限: operator, admin

- **DELETE** `/api/v1/backups/backups/{backup_id}` - バックアップ削除
  - 権限: operator, admin

### バックアップスケジューラ
- **GET** `/api/v1/backups/scheduler/status` - スケジューラ状態取得
  - 権限: admin

- **POST** `/api/v1/backups/scheduler/servers/{server_id}/schedule` - サーバーのスケジュール追加
  - Query: `interval_hours`, `max_backups`
  - 権限: admin

- **PUT** `/api/v1/backups/scheduler/servers/{server_id}/schedule` - サーバーのスケジュール更新
  - Query: `interval_hours`, `max_backups`, `enabled`
  - 権限: admin

- **DELETE** `/api/v1/backups/scheduler/servers/{server_id}/schedule` - サーバーのスケジュール削除
  - 権限: admin

## 📄 テンプレート管理

### テンプレート操作
- **POST** `/api/v1/templates` - カスタムテンプレート作成
  - Body: `TemplateCreateCustomRequest`
  - Response: `TemplateResponse`
  - 権限: operator, admin

- **POST** `/api/v1/templates/from-server/{server_id}` - サーバーからテンプレート作成
  - Body: `TemplateCreateFromServerRequest`
  - Response: `TemplateResponse`
  - 権限: operator, admin

- **GET** `/api/v1/templates` - テンプレート一覧
  - Query: `page`, `size`, `minecraft_version`, `server_type`, `is_public`
  - Response: `TemplateListResponse`
  - 権限: 全ユーザー（アクセス権フィルタ適用）

- **GET** `/api/v1/templates/{template_id}` - テンプレート詳細
  - Response: `TemplateResponse`
  - 権限: 所有者, admin, または公開テンプレート

- **PUT** `/api/v1/templates/{template_id}` - テンプレート更新
  - Body: `TemplateUpdateRequest`
  - Response: `TemplateResponse`
  - 権限: 所有者, admin

- **DELETE** `/api/v1/templates/{template_id}` - テンプレート削除
  - 権限: 所有者, admin

- **POST** `/api/v1/templates/{template_id}/clone` - テンプレートクローン
  - Query: `name`, `description`, `is_public`
  - Response: `TemplateResponse`
  - 権限: 全ユーザー（アクセス可能なテンプレート）

- **GET** `/api/v1/templates/statistics` - テンプレート統計
  - Response: `TemplateStatisticsResponse`
  - 権限: 全ユーザー

## 📁 ファイル管理

### ファイル操作（RESTful形式）
- **GET** `/api/v1/files/servers/{server_id}/files` - ルートディレクトリのファイル一覧
- **GET** `/api/v1/files/servers/{server_id}/files/{path}` - 指定パスのファイル一覧
  - Query: `file_type`
  - Response: `FileListResponse`
  - 権限: 所有者, admin

- **GET** `/api/v1/files/servers/{server_id}/files/{file_path}/read` - ファイル内容読み取り
  - Query: `encoding`
  - Response: `FileReadResponse`
  - 権限: 所有者, admin

- **PUT** `/api/v1/files/servers/{server_id}/files/{file_path}` - ファイル書き込み
  - Body: `FileWriteRequest`
  - Response: `FileWriteResponse`
  - 権限: 所有者, admin（制限ファイル: admin専用）

- **DELETE** `/api/v1/files/servers/{server_id}/files/{file_path}` - ファイル/ディレクトリ削除
  - Response: `FileDeleteResponse`
  - 権限: 所有者, admin（制限ファイル: admin専用）

- **POST** `/api/v1/files/servers/{server_id}/files/upload` - ファイルアップロード
  - Form: `file`, `destination_path`, `extract_if_archive`
  - Response: `FileUploadResponse`
  - 権限: 所有者, admin

- **GET** `/api/v1/files/servers/{server_id}/files/{file_path}/download` - ファイルダウンロード
  - Response: ファイルダウンロード
  - 権限: 所有者, admin

- **POST** `/api/v1/files/servers/{server_id}/files/{directory_path}/directories` - ディレクトリ作成
  - Body: `DirectoryCreateRequest`
  - Response: `DirectoryCreateResponse`
  - 権限: 所有者, admin

- **POST** `/api/v1/files/servers/{server_id}/files/search` - ファイル検索
  - Body: `FileSearchRequest`
  - Response: `FileSearchResponse`
  - 権限: 所有者, admin

## 🔌 WebSocket通信

### リアルタイム通信
- **WebSocket** `/api/v1/ws/server/{server_id}/logs` - リアルタイムサーバーログ
  - 権限: 所有者, admin

- **WebSocket** `/api/v1/ws/server/{server_id}/status` - リアルタイム状態更新
  - 権限: 所有者, admin

- **WebSocket** `/api/v1/ws/notifications` - グローバル通知
  - 権限: 認証済み

## 🛡️ セキュリティとアクセス制御

### ユーザーロール
1. **user** - 基本ロール（閲覧のみ）
2. **operator** - サーバー管理権限
3. **admin** - システム全体管理権限

### アクセス制御ルール
- **サーバーアクセス**: 所有者またはadminのみ
- **グループアクセス**: 作成者またはadminのみ
- **バックアップアクセス**: サーバー所有者またはadminのみ
- **テンプレートアクセス**: 公開テンプレート、自作テンプレート、adminは全て
- **ファイルアクセス**: サーバーアクセス権と同様、システムファイルは追加制限

## 📊 レスポンス形式

### HTTPステータスコード
- **200** - 成功
- **201** - 作成成功
- **204** - 削除成功（レスポンスボディなし）
- **400** - リクエストエラー
- **401** - 認証必須
- **403** - アクセス権限不足
- **404** - リソースが見つからない
- **409** - リソース競合
- **422** - バリデーションエラー
- **500** - サーバーエラー

### 成功レスポンス例
```json
{
  "id": 1,
  "name": "MyServer",
  "status": "running",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### ページネーション例
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "size": 20
}
```

### エラーレスポンス例
```json
{
  "detail": "Server not found"
}
```

## 🚀 使用例

### サーバー作成からグループ適用まで
1. テンプレート一覧取得: `GET /api/v1/templates`
2. サーバー作成: `POST /api/v1/servers`
3. グループ作成: `POST /api/v1/groups`
4. グループをサーバーに適用: `POST /api/v1/groups/{group_id}/servers`
5. サーバー開始: `POST /api/v1/servers/{server_id}/start`

### バックアップからの復元
1. バックアップ一覧: `GET /api/v1/backups/servers/{server_id}/backups`
2. バックアップ復元: `POST /api/v1/backups/backups/{backup_id}/restore`