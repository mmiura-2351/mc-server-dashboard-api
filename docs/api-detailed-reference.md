# API詳細リファレンス - Minecraft Server Dashboard

本ドキュメントは、Minecraft Server Dashboard APIの詳細な実装リファレンスです。
フロントエンド等のクライアントアプリケーション開発のための正確な仕様を提供します。

## 目次

1. [概要](#概要)
2. [認証システム](#認証システム)
3. [ユーザー管理](#ユーザー管理)
4. [サーバー管理](#サーバー管理)
5. [グループ管理](#グループ管理)
6. [バックアップ管理](#バックアップ管理)
7. [テンプレート管理](#テンプレート管理)
8. [ファイル管理](#ファイル管理)
9. [WebSocket通信](#websocket通信)
10. [エラーハンドリング](#エラーハンドリング)

## 概要

### ベースURL
`/api/v1/`

### 認証方式
JWT Bearerトークン認証を使用。ログインエンドポイントで取得したトークンを以下のヘッダーで送信：
```
Authorization: Bearer <access_token>
```

### ユーザーロール
- **user**: 基本権限（閲覧のみ）
- **operator**: サーバー作成・管理権限
- **admin**: システム全体の管理権限

## 認証システム

### POST /auth/token
**ユーザーログイン**

OAuth2 PasswordRequestForm形式でのログイン認証を行います。

**リクエスト**
- Content-Type: `application/x-www-form-urlencoded`
- Body:
  - `username`: ユーザー名（必須）
  - `password`: パスワード（必須）

**レスポンス**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**処理詳細**
1. UserServiceを使用してユーザー認証を実行
2. ユーザーが存在し、パスワードが正しい場合のみ認証成功
3. ユーザーが承認されていない（is_approved=false）場合は403エラー
4. ユーザーがアクティブでない（is_active=false）場合は403エラー
5. 認証成功時、JWTトークンを生成（有効期限はデフォルト30分）

**エラーレスポンス**
- 401: 無効なユーザー名またはパスワード
- 403: ユーザーが未承認またはアクティブでない

## ユーザー管理

### POST /users/register
**ユーザー登録**

新規ユーザーアカウントを作成します。

**リクエスト**
```json
{
  "username": "newuser",
  "email": "user@example.com",
  "password": "securepassword"
}
```

**レスポンス**
```json
{
  "id": 1,
  "username": "newuser",
  "email": "user@example.com",
  "is_active": true,
  "is_approved": false,
  "role": "user"
}
```

**処理詳細**
1. ユーザー名とメールアドレスの重複チェック
2. パスワードをbcryptでハッシュ化
3. デフォルトロール「user」で作成
4. is_active=true、is_approved=falseで作成（管理者承認が必要）
5. データベースに保存

**エラー**
- 409: ユーザー名またはメールアドレスが既に存在

### POST /users/approve/{user_id}
**ユーザー承認**

管理者が新規ユーザーを承認します。

**権限**: admin

**パスパラメータ**
- `user_id`: 承認するユーザーのID

**レスポンス**
```json
{
  "id": 1,
  "username": "newuser",
  "email": "user@example.com",
  "is_active": true,
  "is_approved": true,
  "role": "user"
}
```

**処理詳細**
1. 指定されたユーザーの存在確認
2. is_approved=trueに更新
3. 更新されたユーザー情報を返却

**エラー**
- 403: 管理者権限がない
- 404: ユーザーが存在しない

### PUT /users/role/{user_id}
**ユーザーロール変更**

ユーザーの権限ロールを変更します。

**権限**: admin

**パスパラメータ**
- `user_id`: 対象ユーザーのID

**リクエスト**
```json
{
  "role": "operator"
}
```

**レスポンス**
```json
{
  "id": 1,
  "username": "user",
  "email": "user@example.com",
  "is_active": true,
  "is_approved": true,
  "role": "operator"
}
```

**処理詳細**
1. 対象ユーザーの存在確認
2. 自分自身のロールは変更不可
3. ロールを更新（user/operator/admin）
4. 更新されたユーザー情報を返却

**エラー**
- 403: 管理者権限がない、または自分自身のロール変更
- 404: ユーザーが存在しない

### GET /users/me
**現在のユーザー情報取得**

認証トークンから現在のユーザー情報を取得します。

**レスポンス**
```json
{
  "id": 1,
  "username": "currentuser",
  "email": "current@example.com",
  "is_active": true,
  "is_approved": true,
  "role": "operator"
}
```

### PUT /users/me
**ユーザー情報更新**

自分のユーザー名とメールアドレスを更新します。

**リクエスト**
```json
{
  "username": "newusername",
  "email": "newemail@example.com"
}
```

**レスポンス**
```json
{
  "user": {
    "id": 1,
    "username": "newusername",
    "email": "newemail@example.com",
    "is_active": true,
    "is_approved": true,
    "role": "operator"
  },
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**処理詳細**
1. 新しいユーザー名/メールアドレスの重複チェック
2. ユーザー情報を更新
3. ユーザー名が変更された場合、新しいJWTトークンを発行
4. 更新されたユーザー情報と新しいトークンを返却

**エラー**
- 409: ユーザー名またはメールアドレスが既に使用されている

### PUT /users/me/password
**パスワード変更**

自分のパスワードを変更します。

**リクエスト**
```json
{
  "current_password": "oldpassword",
  "new_password": "newpassword"
}
```

**レスポンス**
```json
{
  "user": {
    "id": 1,
    "username": "user",
    "email": "user@example.com",
    "is_active": true,
    "is_approved": true,
    "role": "operator"
  },
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**処理詳細**
1. 現在のパスワードの検証
2. 新しいパスワードをbcryptでハッシュ化
3. パスワードを更新
4. 新しいJWTトークンを発行

**エラー**
- 401: 現在のパスワードが正しくない

### DELETE /users/me
**アカウント削除**

自分のアカウントを削除します。

**リクエスト**
```json
{
  "password": "currentpassword"
}
```

**レスポンス**
```json
{
  "message": "Account deleted successfully"
}
```

**処理詳細**
1. パスワードの検証
2. ユーザーをデータベースから物理削除
3. 関連するすべてのデータも削除される

**エラー**
- 401: パスワードが正しくない

### GET /users/
**全ユーザー一覧**

システム内のすべてのユーザーを取得します。

**権限**: admin

**レスポンス**
```json
[
  {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "is_active": true,
    "is_approved": true,
    "role": "admin"
  },
  {
    "id": 2,
    "username": "operator1",
    "email": "operator1@example.com",
    "is_active": true,
    "is_approved": true,
    "role": "operator"
  }
]
```

### DELETE /users/{user_id}
**ユーザー削除（管理者）**

指定したユーザーを削除します。

**権限**: admin

**パスパラメータ**
- `user_id`: 削除するユーザーのID

**レスポンス**
```json
{
  "message": "User deleted successfully"
}
```

**処理詳細**
1. 自分自身は削除不可
2. ユーザーを物理削除
3. 関連データも削除される

**エラー**
- 403: 管理者権限がない、または自分自身を削除しようとした
- 404: ユーザーが存在しない

## サーバー管理

### POST /servers
**サーバー作成**

新しいMinecraftサーバーを作成します。

**権限**: operator, admin

**リクエスト**
```json
{
  "name": "test-server",
  "description": "Test server created from API tester",
  "minecraft_version": "1.20.1",
  "server_type": "vanilla",
  "port": 25565,
  "max_memory": 1024,
  "max_players": 20,
  "template_id": null,
  "server_properties": {
    "difficulty": "normal",
    "gamemode": "survival",
    "pvp": true
  },
  "attach_groups": {
    "op_groups": [1, 2],
    "whitelist_groups": [3]
  }
}
```

**レスポンス**
```json
{
  "id": 1,
  "name": "My Server",
  "description": "A test server",
  "minecraft_version": "1.20.1",
  "server_type": "vanilla",
  "status": "stopped",
  "directory_path": "/servers/server_1",
  "port": 25565,
  "max_memory": 2048,
  "max_players": 20,
  "owner_id": 1,
  "template_id": null,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "process_info": null,
  "configurations": []
}
```

**処理詳細**
1. サーバー名の重複チェック（ユーザーごと）
2. ポート番号の使用状況チェック
3. テンプレートが指定された場合、テンプレートから設定をコピー
4. サーバーディレクトリを作成
5. Minecraft ServerのJARファイルをダウンロード
6. server.propertiesファイルを生成
7. 指定されたグループを自動的にアタッチ
8. データベースに保存

**必須フィールド**
- `name`: サーバー名（1-100文字、英数字・スペース・ハイフン・アンダースコアのみ）
- `minecraft_version`: Minecraftバージョン（X.Y.Z形式、例: 1.20.1、最小1.8.0）
- `server_type`: サーバータイプ（vanilla, forge, paper）

**オプションフィールド**
- `description`: サーバー説明文（最大500文字）
- `port`: ポート番号（1024-65535、デフォルト: 25565）
- `max_memory`: 最大メモリ（512-16384 MB、デフォルト: 1024）
- `max_players`: 最大プレイヤー数（1-100、デフォルト: 20）
- `template_id`: テンプレートID（存在するテンプレートのみ）
- `server_properties`: サーバープロパティ（有効なプロパティキーのみ許可）
- `attach_groups`: アタッチするグループ（op_groups, whitelist_groups）

**エラー**
- 403: ユーザーロールがuserの場合
- 409: サーバー名またはポートが既に使用されている
- 404: 指定されたテンプレートが存在しない
- 422: バリデーションエラー（必須フィールド不足、形式エラー、範囲外の値など）

### GET /servers
**サーバー一覧取得**

ページネーション付きでサーバー一覧を取得します。

**クエリパラメータ**
- `page`: ページ番号（デフォルト: 1）
- `size`: ページサイズ（デフォルト: 50、最大: 100）

**レスポンス**
```json
{
  "servers": [
    {
      "id": 1,
      "name": "My Server",
      "description": "A test server",
      "minecraft_version": "1.20.1",
      "server_type": "vanilla",
      "status": "running",
      "directory_path": "/servers/server_1",
      "port": 25565,
      "max_memory": 2048,
      "max_players": 20,
      "owner_id": 1,
      "template_id": null,
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z",
      "process_info": {
        "pid": 12345,
        "memory_usage": 1024,
        "cpu_usage": 15.5,
        "uptime": 3600
      },
      "configurations": []
    }
  ],
  "total": 10,
  "page": 1,
  "size": 50
}
```

**処理詳細**
1. 管理者の場合：すべてのサーバーを表示
2. 一般ユーザーの場合：自分が所有するサーバーのみ表示
3. 削除済みサーバーは表示されない
4. 各サーバーの現在のプロセス情報を取得

### GET /servers/{server_id}
**サーバー詳細取得**

指定されたサーバーの詳細情報を取得します。

**権限**: 所有者またはadmin

**パスパラメータ**
- `server_id`: サーバーID

**レスポンス**
サーバー一覧と同じサーバーオブジェクト形式

**処理詳細**
1. サーバーの存在確認
2. アクセス権限の確認（所有者またはadmin）
3. サーバーの詳細情報を取得
4. リアルタイムのプロセス情報を含めて返却

### PUT /servers/{server_id}
**サーバー更新**

サーバーの設定を更新します。

**権限**: 所有者またはadmin

**パスパラメータ**
- `server_id`: サーバーID

**リクエスト**
```json
{
  "name": "Updated Server Name",
  "description": "Updated description",
  "max_memory": 4096,
  "max_players": 50,
  "server_properties": {
    "difficulty": "hard",
    "pvp": false
  }
}
```

**処理詳細**
1. サーバーのアクセス権限確認
2. サーバーが実行中の場合、max_memoryとserver_propertiesの更新は不可
3. 基本情報（name、description）は常に更新可能
4. server_propertiesが指定された場合、server.propertiesファイルを更新
5. データベースを更新

**エラー**
- 403: アクセス権限がない
- 404: サーバーが存在しない
- 409: サーバーが実行中で更新できない項目がある

### DELETE /servers/{server_id}
**サーバー削除**

サーバーをソフトデリート（論理削除）します。

**権限**: 所有者またはadmin

**パスパラメータ**
- `server_id`: サーバーID

**処理詳細**
1. サーバーのアクセス権限確認
2. サーバーが実行中の場合は停止
3. サーバーを論理削除（is_deleted=trueに設定）
4. サーバーファイルは保持される（物理削除はしない）
5. クライアントからは完全に削除されたように見える
6. ステータスコード204を返却（レスポンスボディなし）

### POST /servers/{server_id}/start
**サーバー起動**

サーバープロセスを起動します。

**権限**: 所有者またはadmin

**レスポンス**
```json
{
  "server_id": 1,
  "status": "starting",
  "process_info": null
}
```

**処理詳細**
1. サーバーのアクセス権限確認
2. 現在のステータスを確認（stopped/errorのみ起動可能）
3. JavaプロセスでMinecraftサーバーを起動
4. ステータスを「starting」に更新
5. プロセスモニタリングを開始
6. サーバーが完全に起動したら「running」に更新

**エラー**
- 409: サーバーが既に起動中または起動処理中

### POST /servers/{server_id}/stop
**サーバー停止**

サーバープロセスを停止します。

**権限**: 所有者またはadmin

**クエリパラメータ**
- `force`: 強制停止フラグ（デフォルト: false）

**レスポンス**
```json
{
  "message": "Server stop initiated"
}
```

**処理詳細**
1. サーバーのアクセス権限確認
2. force=falseの場合：「stop」コマンドを送信して正常停止
3. force=trueの場合：プロセスを強制終了
4. ステータスを「stopping」に更新
5. プロセスが完全に停止したら「stopped」に更新

**エラー**
- 409: サーバーが既に停止している

### POST /servers/{server_id}/restart
**サーバー再起動**

サーバーを停止してから再起動します。

**権限**: 所有者またはadmin

**処理詳細**
1. サーバーのアクセス権限確認
2. サーバーが実行中の場合は停止
3. 停止完了まで待機（最大30秒）
4. サーバーを起動

### GET /servers/{server_id}/status
**サーバーステータス取得**

サーバーの現在のステータスとプロセス情報を取得します。

**権限**: 所有者またはadmin

**レスポンス**
```json
{
  "server_id": 1,
  "status": "running",
  "process_info": {
    "pid": 12345,
    "memory_usage": 1536,
    "cpu_usage": 25.5,
    "uptime": 7200,
    "player_count": 5,
    "max_players": 20,
    "tps": 19.8
  }
}
```

**処理詳細**
1. データベースからステータスを取得
2. プロセスマネージャーから詳細情報を取得
3. プレイヤー数やTPSなどのゲーム内情報も含める

### POST /servers/{server_id}/command
**コンソールコマンド送信**

実行中のサーバーにコンソールコマンドを送信します。

**権限**: 所有者またはadmin

**リクエスト**
```json
{
  "command": "say Hello World!"
}
```

**レスポンス**
```json
{
  "message": "Command 'say Hello World!' sent to server"
}
```

**処理詳細**
1. サーバーのアクセス権限確認
2. サーバーが実行中であることを確認
3. 危険なコマンド（stop、restart、shutdown）をブロック
4. コマンドをサーバープロセスの標準入力に送信

**エラー**
- 400: 危険なコマンドの送信
- 409: サーバーが実行中でない

### GET /servers/{server_id}/logs
**サーバーログ取得**

サーバーの最新ログを取得します。

**権限**: 所有者またはadmin

**クエリパラメータ**
- `lines`: 取得する行数（1-1000、デフォルト: 100）

**レスポンス**
```json
{
  "server_id": 1,
  "logs": [
    "[14:30:00] [Server thread/INFO]: Starting minecraft server version 1.20.1",
    "[14:30:01] [Server thread/INFO]: Loading properties",
    "[14:30:02] [Server thread/INFO]: Default game type: SURVIVAL"
  ],
  "total_lines": 3
}
```

**処理詳細**
1. サーバーのアクセス権限確認
2. logs/latest.logファイルから最新のN行を読み取り
3. ログの配列として返却

### GET /servers/versions/supported
**サポートバージョン一覧**

サポートされているMinecraftバージョンとサーバータイプの一覧を取得します。

**権限**: 認証が必要

**レスポンス**
```json
{
  "versions": [
    {
      "version": "1.20.1",
      "server_type": "vanilla",
      "download_url": "https://...",
      "is_supported": true,
      "release_date": "2023-06-12T00:00:00Z",
      "is_stable": true,
      "build_number": null
    },
    {
      "version": "1.20.1",
      "server_type": "paper",
      "download_url": "https://...",
      "is_supported": true,
      "release_date": "2023-06-12T00:00:00Z",
      "is_stable": true,
      "build_number": 196
    },
    {
      "version": "1.19.4",
      "server_type": "forge",
      "download_url": "https://...",
      "is_supported": true,
      "release_date": "2023-03-14T00:00:00Z",
      "is_stable": true,
      "build_number": null
    }
  ]
}
```

**処理詳細**
1. 動的バージョン管理システムから最新のサポート情報を取得
2. 各サーバータイプ（vanilla, paper, forge）の利用可能バージョンを確認
3. 最小サポートバージョン（1.8.0）以上のみを返却
4. ダウンロードURLとビルド番号（該当する場合）を含む

### POST /servers/sync
**サーバー状態同期**

データベースとプロセスマネージャー間でサーバー状態を同期します。

**権限**: admin

**レスポンス**
```json
{
  "message": "Server states synchronized",
  "running_servers": [1, 3, 5],
  "total_running": 3
}
```

**処理詳細**
1. すべてのサーバーのデータベース状態を確認
2. 実際のプロセス状態と比較
3. 不整合があれば修正
4. 実行中のサーバーIDリストを返却

## グループ管理

### POST /groups
**グループ作成**

OPまたはホワイトリストのプレイヤーグループを作成します。

**権限**: operator, admin

**リクエスト**
```json
{
  "name": "Administrators",
  "group_type": "op",
  "description": "Server administrators group"
}
```

**レスポンス**
```json
{
  "id": 1,
  "name": "Administrators",
  "group_type": "op",
  "description": "Server administrators group",
  "owner_id": 1,
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "players": []
}
```

**処理詳細**
1. グループ名の重複チェック（ユーザーごと）
2. group_typeの検証（op/whitelist）
3. データベースに保存

### GET /groups
**グループ一覧取得**

所有するグループの一覧を取得します。

**クエリパラメータ**
- `group_type`: フィルタリング（op/whitelist）

**レスポンス**
```json
{
  "groups": [
    {
      "id": 1,
      "name": "Administrators",
      "group_type": "op",
      "description": "Server administrators group",
      "owner_id": 1,
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z",
      "players": [
        {
          "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
          "username": "Notch"
        }
      ]
    }
  ],
  "total": 1
}
```

### GET /groups/{group_id}
**グループ詳細取得**

指定されたグループの詳細を取得します。

**権限**: 所有者またはadmin

### PUT /groups/{group_id}
**グループ更新**

グループの名前と説明を更新します。

**権限**: 所有者またはadmin

**リクエスト**
```json
{
  "name": "Updated Group Name",
  "description": "Updated description"
}
```

**注意**: group_typeは変更できません

### DELETE /groups/{group_id}
**グループ削除**

グループを削除します。

**権限**: 所有者またはadmin

**処理詳細**
1. グループがサーバーにアタッチされていないことを確認
2. グループとすべてのプレイヤー関連を削除

**エラー**
- 409: グループがサーバーにアタッチされている

### POST /groups/{group_id}/players
**プレイヤー追加**

グループにプレイヤーを追加します。

**権限**: 所有者またはadmin

**リクエスト**
```json
{
  "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5",
  "username": "Notch"
}
```

**処理詳細**
1. グループの所有権確認
2. プレイヤーが既に存在する場合はユーザー名を更新
3. グループに追加
4. アタッチされているすべてのサーバーのファイルを更新

### DELETE /groups/{group_id}/players/{player_uuid}
**プレイヤー削除**

グループからプレイヤーを削除します。

**権限**: 所有者またはadmin

**処理詳細**
1. グループの所有権確認
2. プレイヤーをグループから削除
3. アタッチされているすべてのサーバーのファイルを更新

### POST /groups/{group_id}/servers
**サーバーへグループをアタッチ**

グループをサーバーに適用します。

**権限**: サーバーとグループの両方の所有者またはadmin

**リクエスト**
```json
{
  "server_id": 1,
  "priority": 100
}
```

**処理詳細**
1. グループとサーバーの所有権確認
2. 同じタイプのグループが既にアタッチされていないか確認
3. 関連を作成（priorityで優先順位を設定）
4. サーバーのops.json/whitelist.jsonファイルを更新

### DELETE /groups/{group_id}/servers/{server_id}
**サーバーからグループをデタッチ**

グループをサーバーから削除します。

**権限**: サーバーとグループの両方の所有者またはadmin

**処理詳細**
1. 関連を削除
2. サーバーのops.json/whitelist.jsonファイルを更新

### GET /groups/{group_id}/servers
**グループがアタッチされているサーバー一覧**

グループが適用されているサーバーの一覧を取得します。

**権限**: グループ所有者またはadmin

**レスポンス**
```json
{
  "group_id": 1,
  "servers": [
    {
      "server_id": 1,
      "server_name": "My Server",
      "priority": 100,
      "attached_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

### GET /groups/servers/{server_id}
**サーバーにアタッチされているグループ一覧**

サーバーに適用されているグループの一覧を取得します。

**権限**: サーバー所有者またはadmin

**レスポンス**
```json
{
  "server_id": 1,
  "groups": [
    {
      "group_id": 1,
      "group_name": "Administrators",
      "group_type": "op",
      "priority": 100,
      "player_count": 5,
      "attached_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

## バックアップ管理

### POST /backups/servers/{server_id}/backups
**バックアップ作成**

サーバーのバックアップを作成します。

**権限**: operator, admin（サーバー所有者）

**リクエスト**
```json
{
  "name": "Before Update",
  "description": "Backup before updating to 1.20.2",
  "backup_type": "manual"
}
```

**レスポンス**
```json
{
  "id": 1,
  "server_id": 1,
  "name": "Before Update",
  "description": "Backup before updating to 1.20.2",
  "backup_type": "manual",
  "file_path": "/backups/server_1_20240101_120000.zip",
  "file_size": 104857600,
  "status": "completed",
  "created_at": "2024-01-01T12:00:00Z",
  "completed_at": "2024-01-01T12:05:00Z"
}
```

**処理詳細**
1. サーバーのアクセス権限確認
2. バックアップディレクトリを作成
3. サーバーディレクトリ全体をZIP圧縮
4. メタデータをデータベースに保存
5. バックアップタイプ：manual（手動）、scheduled（定期）、pre_update（更新前）

### GET /backups/servers/{server_id}/backups
**サーバーバックアップ一覧**

特定のサーバーのバックアップ一覧を取得します。

**権限**: サーバー所有者またはadmin

**クエリパラメータ**
- `page`: ページ番号
- `size`: ページサイズ
- `backup_type`: フィルタリング（manual/scheduled/pre_update）

**レスポンス**
```json
{
  "backups": [
    {
      "id": 1,
      "server_id": 1,
      "name": "Before Update",
      "description": "Backup before updating to 1.20.2",
      "backup_type": "manual",
      "file_path": "/backups/server_1_20240101_120000.zip",
      "file_size": 104857600,
      "status": "completed",
      "created_at": "2024-01-01T12:00:00Z",
      "completed_at": "2024-01-01T12:05:00Z"
    }
  ],
  "total": 10,
  "page": 1,
  "size": 50
}
```

### GET /backups/backups
**全バックアップ一覧（管理者）**

システム内のすべてのバックアップを取得します。

**権限**: admin

### GET /backups/backups/{backup_id}
**バックアップ詳細**

指定されたバックアップの詳細を取得します。

**権限**: バックアップのサーバー所有者またはadmin

### POST /backups/backups/{backup_id}/restore
**バックアップ復元**

バックアップをサーバーに復元します。

**権限**: operator, admin（サーバー所有者）

**リクエスト**
```json
{
  "target_server_id": 1,
  "confirm": true
}
```

**レスポンス**
```json
{
  "success": true,
  "message": "Backup 1 restored successfully to server 1",
  "backup_id": 1,
  "details": {
    "target_server_id": 1
  }
}
```

**処理詳細**
1. バックアップとターゲットサーバーのアクセス権限確認
2. ターゲットサーバーが停止していることを確認
3. 現在のサーバーディレクトリをバックアップ
4. バックアップファイルを解凍してサーバーディレクトリに復元
5. データベースのサーバー情報を更新

**エラー**
- 409: サーバーが実行中

### POST /backups/backups/{backup_id}/restore-with-template
**バックアップ復元＋テンプレート作成**

バックアップを復元し、同時にテンプレートを作成します。

**権限**: operator, admin（サーバー所有者）

**リクエスト**
```json
{
  "target_server_id": 1,
  "confirm": true,
  "template_name": "Stable Configuration",
  "template_description": "Stable server configuration",
  "is_public": false
}
```

**レスポンス**
```json
{
  "backup_restored": true,
  "template_created": true,
  "message": "Backup 1 restored successfully to server 1 and template 'Stable Configuration' created",
  "backup_id": 1,
  "template_id": 5,
  "template_name": "Stable Configuration",
  "details": {
    "target_server_id": 1,
    "template_description": "Stable server configuration",
    "is_public": false
  }
}
```

**処理詳細**
1. バックアップ復元を実行
2. 復元したサーバーからテンプレートを作成
3. 両方の操作結果を返却

### DELETE /backups/backups/{backup_id}
**バックアップ削除**

バックアップを削除します。

**権限**: operator, admin（サーバー所有者）

**処理詳細**
1. バックアップのアクセス権限確認
2. バックアップファイルを物理削除
3. データベースレコードを削除

### GET /backups/servers/{server_id}/backups/statistics
**サーバーバックアップ統計**

サーバーのバックアップ統計情報を取得します。

**権限**: サーバー所有者またはadmin

**レスポンス**
```json
{
  "server_id": 1,
  "total_backups": 25,
  "total_size": 2147483648,
  "backup_types": {
    "manual": 10,
    "scheduled": 14,
    "pre_update": 1
  },
  "success_rate": 96.0,
  "average_size": 85899345,
  "latest_backup": "2024-01-01T12:00:00Z",
  "oldest_backup": "2023-12-01T00:00:00Z"
}
```

### GET /backups/scheduler/status
**バックアップスケジューラー状態**

自動バックアップスケジューラーの状態を取得します。

**権限**: admin

**レスポンス**
```json
{
  "scheduler_running": true,
  "scheduled_servers": [
    {
      "server_id": 1,
      "server_name": "My Server",
      "interval_hours": 24,
      "max_backups": 7,
      "enabled": true,
      "last_backup": "2024-01-01T00:00:00Z",
      "next_backup": "2024-01-02T00:00:00Z"
    }
  ],
  "total_scheduled": 5
}
```

### POST /backups/scheduler/servers/{server_id}/schedule
**サーバーのバックアップスケジュール追加**

サーバーを自動バックアップスケジュールに追加します。

**権限**: admin

**クエリパラメータ**
- `interval_hours`: バックアップ間隔（1-168時間）
- `max_backups`: 保持する最大バックアップ数（1-30）

**レスポンス**
```json
{
  "message": "Server 1 added to backup schedule",
  "interval_hours": 24,
  "max_backups": 7
}
```

### PUT /backups/scheduler/servers/{server_id}/schedule
**バックアップスケジュール更新**

サーバーのバックアップスケジュールを更新します。

**権限**: admin

**クエリパラメータ**
- `interval_hours`: バックアップ間隔（オプション）
- `max_backups`: 最大バックアップ数（オプション）
- `enabled`: スケジュールの有効/無効（オプション）

### DELETE /backups/scheduler/servers/{server_id}/schedule
**バックアップスケジュール削除**

サーバーを自動バックアップスケジュールから削除します。

**権限**: admin

## テンプレート管理

### POST /templates
**カスタムテンプレート作成**

新規にカスタムテンプレートを作成します。

**権限**: operator, admin

**リクエスト**
```json
{
  "name": "PvP Server Template",
  "minecraft_version": "1.20.1",
  "server_type": "paper",
  "configuration": {
    "server_properties": {
      "pvp": true,
      "difficulty": "hard",
      "gamemode": "survival"
    },
    "plugins": ["EssentialsX", "WorldEdit"],
    "custom_files": {}
  },
  "description": "Template for PvP servers",
  "default_groups": {
    "op_groups": [1],
    "whitelist_groups": [2]
  },
  "is_public": true
}
```

**レスポンス**
```json
{
  "id": 1,
  "name": "PvP Server Template",
  "minecraft_version": "1.20.1",
  "server_type": "paper",
  "description": "Template for PvP servers",
  "is_public": true,
  "creator_id": 1,
  "file_path": "/templates/template_1",
  "created_at": "2024-01-01T00:00:00Z",
  "updated_at": "2024-01-01T00:00:00Z",
  "usage_count": 0
}
```

**処理詳細**
1. テンプレート名の重複チェック
2. テンプレートディレクトリを作成
3. 設定情報をJSON形式で保存
4. データベースに登録

### POST /templates/from-server/{server_id}
**サーバーからテンプレート作成**

既存のサーバー設定からテンプレートを作成します。

**権限**: operator, admin（サーバー所有者）

**リクエスト**
```json
{
  "name": "My Server Template",
  "description": "Template based on my production server",
  "is_public": false
}
```

**処理詳細**
1. サーバーのアクセス権限確認
2. サーバーディレクトリから必要なファイルをコピー
3. server.propertiesを解析して設定を抽出
4. プラグイン/MODリストを収集
5. テンプレートとして保存

### GET /templates
**テンプレート一覧**

利用可能なテンプレートの一覧を取得します。

**クエリパラメータ**
- `minecraft_version`: バージョンでフィルタ
- `server_type`: サーバータイプでフィルタ
- `is_public`: 公開/非公開でフィルタ
- `page`: ページ番号
- `size`: ページサイズ

**レスポンス**
```json
{
  "templates": [
    {
      "id": 1,
      "name": "PvP Server Template",
      "minecraft_version": "1.20.1",
      "server_type": "paper",
      "description": "Template for PvP servers",
      "is_public": true,
      "creator_id": 1,
      "created_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z",
      "usage_count": 5
    }
  ],
  "total": 10,
  "page": 1,
  "size": 50
}
```

**アクセスルール**
- 公開テンプレート：全ユーザーが閲覧可能
- 非公開テンプレート：作成者のみ閲覧可能
- 管理者：すべてのテンプレートを閲覧可能

### GET /templates/{template_id}
**テンプレート詳細**

テンプレートの詳細情報を取得します。

**権限**: 公開テンプレートまたは作成者またはadmin

### PUT /templates/{template_id}
**テンプレート更新**

テンプレートの情報を更新します。

**権限**: 作成者またはadmin

**リクエスト**
```json
{
  "name": "Updated Template Name",
  "description": "Updated description",
  "configuration": {
    "server_properties": {
      "pvp": false
    }
  },
  "default_groups": {
    "op_groups": [1, 2]
  },
  "is_public": true
}
```

### DELETE /templates/{template_id}
**テンプレート削除**

テンプレートを削除します。

**権限**: 作成者またはadmin

**処理詳細**
1. テンプレートが使用中でないことを確認
2. テンプレートファイルを削除
3. データベースレコードを削除

**エラー**
- 409: テンプレートが現在使用中

### GET /templates/statistics
**テンプレート統計**

テンプレートの使用統計を取得します。

**レスポンス**
```json
{
  "total_templates": 25,
  "public_templates": 15,
  "private_templates": 10,
  "total_usage": 150,
  "templates_by_type": {
    "vanilla": 10,
    "paper": 10,
    "forge": 5
  },
  "most_popular": [
    {
      "id": 1,
      "name": "PvP Server Template",
      "usage_count": 50
    }
  ]
}
```

### POST /templates/{template_id}/clone
**テンプレートクローン**

既存のテンプレートをコピーして新しいテンプレートを作成します。

**権限**: operator, admin（アクセス可能なテンプレート）

**クエリパラメータ**
- `name`: 新しいテンプレート名（必須）
- `description`: 説明（オプション）
- `is_public`: 公開設定（デフォルト: false）

## ファイル管理

### GET /files/servers/{server_id}/files
### GET /files/servers/{server_id}/files/{path}
**ファイル一覧取得**

サーバーディレクトリ内のファイル一覧を取得します。

**権限**: サーバー所有者またはadmin

**クエリパラメータ**
- `file_type`: ファイルタイプでフィルタ（config/log/world/plugin/other）

**レスポンス**
```json
{
  "files": [
    {
      "name": "server.properties",
      "path": "server.properties",
      "type": "file",
      "size": 1024,
      "modified": "2024-01-01T00:00:00Z",
      "permissions": "rw-r--r--",
      "is_editable": true,
      "is_binary": false,
      "file_type": "config"
    },
    {
      "name": "logs",
      "path": "logs",
      "type": "directory",
      "size": 0,
      "modified": "2024-01-01T00:00:00Z",
      "permissions": "rwxr-xr-x",
      "is_editable": false,
      "is_binary": false,
      "file_type": "directory"
    }
  ],
  "current_path": "",
  "total_files": 15
}
```

### GET /files/servers/{server_id}/files/{file_path}/read
**ファイル内容読み取り**

テキストファイルの内容を読み取ります。

**権限**: サーバー所有者またはadmin

**クエリパラメータ**
- `encoding`: 文字エンコーディング（デフォルト: utf-8）

**レスポンス**
```json
{
  "content": "# Minecraft Server Properties\nserver-port=25565\n...",
  "encoding": "utf-8",
  "file_info": {
    "name": "server.properties",
    "path": "server.properties",
    "type": "file",
    "size": 1024,
    "modified": "2024-01-01T00:00:00Z",
    "permissions": "rw-r--r--",
    "is_editable": true,
    "is_binary": false,
    "file_type": "config"
  }
}
```

**処理詳細**
1. ファイルがバイナリでないことを確認
2. ファイルサイズが上限（10MB）以下であることを確認
3. ファイル内容を読み取って返却

### PUT /files/servers/{server_id}/files/{file_path}
**ファイル書き込み**

ファイルに内容を書き込みます。

**権限**: サーバー所有者またはadmin（制限ファイルはadminのみ）

**リクエスト**
```json
{
  "content": "# Updated server properties\nserver-port=25566\n...",
  "encoding": "utf-8",
  "create_backup": true
}
```

**レスポンス**
```json
{
  "success": true,
  "message": "File updated successfully",
  "backup_created": true,
  "backup_path": "server.properties.backup.20240101120000"
}
```

**処理詳細**
1. ファイルの編集権限を確認
2. システムファイルの場合は管理者権限を要求
3. create_backup=trueの場合、変更前のファイルをバックアップ
4. ファイルに内容を書き込み

**制限ファイル（adminのみ）**
- JARファイル
- 実行可能ファイル
- システム設定ファイル

### DELETE /files/servers/{server_id}/files/{file_path}
**ファイル削除**

ファイルまたはディレクトリを削除します。

**権限**: サーバー所有者またはadmin（制限ファイルはadminのみ）

**レスポンス**
```json
{
  "success": true,
  "message": "File deleted successfully",
  "deleted_path": "old-plugin.jar",
  "was_directory": false
}
```

**処理詳細**
1. ファイルの削除権限を確認
2. システムファイルの場合は削除を拒否
3. ディレクトリの場合は再帰的に削除

### POST /files/servers/{server_id}/files/upload
**ファイルアップロード**

サーバーにファイルをアップロードします。

**権限**: サーバー所有者またはadmin

**リクエスト（multipart/form-data）**
- `file`: アップロードするファイル
- `destination_path`: 保存先パス（デフォルト: ルート）
- `extract_if_archive`: ZIPファイルを展開するか（デフォルト: false）

**レスポンス**
```json
{
  "success": true,
  "message": "File uploaded successfully",
  "uploaded_file": "plugin.jar",
  "destination": "plugins/plugin.jar",
  "extracted": false,
  "file_size": 1048576
}
```

**処理詳細**
1. ファイルサイズ制限（100MB）をチェック
2. ファイルタイプの検証
3. ウイルススキャン（実装されている場合）
4. ファイルを指定パスに保存
5. extract_if_archive=trueかつZIPファイルの場合、展開

### GET /files/servers/{server_id}/files/{file_path}/download
**ファイルダウンロード**

ファイルまたはディレクトリ（ZIP圧縮）をダウンロードします。

**権限**: サーバー所有者またはadmin

**レスポンス**
- ファイルの場合：ファイルそのもの
- ディレクトリの場合：ZIP圧縮されたアーカイブ

### POST /files/servers/{server_id}/files/{directory_path}/directories
**ディレクトリ作成**

新しいディレクトリを作成します。

**権限**: サーバー所有者またはadmin

**リクエスト**
```json
{
  "name": "new-plugin-configs"
}
```

**レスポンス**
```json
{
  "success": true,
  "message": "Directory created successfully",
  "path": "plugins/new-plugin-configs",
  "created": true
}
```

### POST /files/servers/{server_id}/files/search
**ファイル検索**

サーバーディレクトリ内でファイルを検索します。

**権限**: サーバー所有者またはadmin

**リクエスト**
```json
{
  "query": "server.properties",
  "file_type": "config",
  "include_content": true,
  "max_results": 50
}
```

**レスポンス**
```json
{
  "results": [
    {
      "file": {
        "name": "server.properties",
        "path": "server.properties",
        "type": "file",
        "size": 1024,
        "modified": "2024-01-01T00:00:00Z",
        "permissions": "rw-r--r--",
        "is_editable": true,
        "is_binary": false,
        "file_type": "config"
      },
      "matches": [
        {
          "line": 15,
          "content": "server-port=25565",
          "highlight": "<mark>server</mark>-port=25565"
        }
      ],
      "match_count": 5
    }
  ],
  "query": "server.properties",
  "total_results": 1,
  "search_time_ms": 45
}
```

## WebSocket通信

### WebSocket /ws/servers/{server_id}/logs
**リアルタイムログストリーミング**

サーバーのログをリアルタイムでストリーミングします。

**権限**: サーバー所有者またはadmin

**クエリパラメータ**
- `token`: JWT認証トークン（必須）

**接続確立後のメッセージ形式**

サーバー→クライアント：
```json
{
  "type": "log",
  "data": {
    "timestamp": "2024-01-01T12:00:00Z",
    "level": "INFO",
    "message": "[Server thread/INFO]: Player joined the game",
    "source": "minecraft"
  }
}
```

```json
{
  "type": "status",
  "data": {
    "server_id": 1,
    "status": "running",
    "process_info": {
      "memory_usage": 1536,
      "cpu_usage": 15.5,
      "player_count": 5
    }
  }
}
```

クライアント→サーバー：
```json
{
  "type": "subscribe",
  "channels": ["logs", "status"]
}
```

### WebSocket /ws/servers/{server_id}/status
**リアルタイムステータス更新**

サーバーのステータスをリアルタイムで受信します。

**権限**: サーバー所有者またはadmin

**メッセージ形式**
ステータス更新のみを配信（ログは含まない）

### WebSocket /ws/notifications
**システム通知**

システム全体の通知を受信します。

**権限**: 認証済みユーザー

**メッセージ形式**
```json
{
  "type": "notification",
  "data": {
    "id": "notif-123",
    "level": "info",
    "title": "Backup Completed",
    "message": "Server 'My Server' backup completed successfully",
    "timestamp": "2024-01-01T12:00:00Z",
    "action": {
      "type": "link",
      "url": "/servers/1/backups"
    }
  }
}
```

## エラーハンドリング

### HTTPステータスコード

- **200 OK**: 成功
- **201 Created**: リソース作成成功
- **204 No Content**: 削除成功（レスポンスボディなし）
- **400 Bad Request**: リクエストエラー
- **401 Unauthorized**: 認証が必要
- **403 Forbidden**: アクセス権限不足
- **404 Not Found**: リソースが見つからない
- **409 Conflict**: リソースの競合
- **422 Unprocessable Entity**: バリデーションエラー
- **500 Internal Server Error**: サーバーエラー

### エラーレスポンス形式

**基本形式**
```json
{
  "detail": "エラーの詳細メッセージ"
}
```

**バリデーションエラー（422）**
```json
{
  "detail": [
    {
      "loc": ["body", "minecraft_version"],
      "msg": "Invalid Minecraft version format. Use format like 1.20.1",
      "type": "value_error"
    }
  ]
}
```

### 共通エラーパターン

1. **認証エラー（401）**
   - トークンが無効または期限切れ
   - トークンが提供されていない

2. **権限エラー（403）**
   - ユーザーが未承認（is_approved=false）
   - ロール権限が不足
   - リソースの所有者でない

3. **リソースエラー（404）**
   - 指定されたIDのリソースが存在しない
   - 削除済みリソースへのアクセス

4. **競合エラー（409）**
   - 重複する名前やポート番号
   - 実行中のサーバーへの不正な操作
   - 使用中のリソースの削除

5. **検証エラー（422）**
   - 必須フィールドの欠落
   - フィールドの形式エラー
   - 値の範囲外

### リトライポリシー

- **5xx エラー**: 指数バックオフでリトライ推奨
- **429 Too Many Requests**: Retry-Afterヘッダーに従う
- **その他の4xx エラー**: リトライ非推奨

## 使用上の注意

1. **認証トークン**
   - トークンの有効期限はデフォルト30分
   - 期限切れ前に更新を推奨
   - ユーザー名変更時は新しいトークンが発行される

2. **リソース制限**
   - APIレート制限: 1分あたり60リクエスト（将来実装予定）
   - ファイルアップロード: 最大100MB
   - ログ取得: 最大1000行

3. **並行性**
   - サーバー操作は排他制御されている
   - 同時に複数の起動/停止操作は不可

4. **データ整合性**
   - ソフトデリート採用でデータの復元が可能
   - 外部キー制約により参照整合性を保証

5. **セキュリティ**
   - システムファイルへのアクセスは制限
   - ファイルパスのトラバーサル攻撃を防止
   - 危険なコマンドの実行をブロック