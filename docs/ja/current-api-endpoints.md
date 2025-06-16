# 現在のAPIエンドポイント - Minecraft Server Dashboard API V1

## 概要

この文書は、Minecraft Server Dashboard API V1で現在実装されているすべてのAPIエンドポイントの包括的なインベントリを提供します。APIはFastAPIで構築され、認証、リアルタイム監視、バックアップ管理、ファイル操作を含む複数のMinecraftサーバー管理のための包括的な機能を提供しています。

## API構造

- **ベースURL**: `/api/v1`
- **認証**: JWT Bearerトークン
- **レスポンス形式**: JSON
- **総エンドポイント数**: 65+
- **ドメイン**: 9の機能ドメイン

## ドメイン概要

| ドメイン | エンドポイント数 | 主要機能 |
|---------|-----------------|----------|
| システム管理 | 2 | ヘルスチェック、メトリクス |
| 認証 | 3 | JWTログイン、リフレッシュ、ログアウト |
| ユーザー管理 | 9 | 登録、承認、プロフィール管理 |
| サーバー管理 | 17 | CRUD、制御、監視、Java互換性 |
| グループ管理 | 9 | OP/ホワイトリストグループ、プレイヤー管理 |
| バックアップ管理 | 10 | 作成、復元、ダウンロード、統計 |
| ファイル管理 | 12 | CRUD、アップロード/ダウンロード、バージョン履歴 |
| WebSocket | 3 | リアルタイムログ、ステータス、通知 |
| 監査ログ | 4 | セキュリティ監視、アクティビティ追跡 |

## 詳細エンドポイントインベントリ

### 1. システム管理

#### ヘルスチェック・監視
```
GET    /health                           # システムヘルスチェック（認証不要）
GET    /metrics                          # パフォーマンスメトリクス（認証不要）
```

### 2. 認証 (`/api/v1/auth`)

```
POST   /api/v1/auth/token               # ユーザーログイン（OAuth2 password flow）
POST   /api/v1/auth/refresh             # アクセストークンリフレッシュ
POST   /api/v1/auth/logout              # ユーザーログアウト
```

### 3. ユーザー管理 (`/api/v1/users`)

#### 登録・承認
```
POST   /api/v1/users/register           # ユーザー登録（認証不要）
POST   /api/v1/users/approve/{user_id}  # ユーザー承認（Admin のみ）
PUT    /api/v1/users/role/{user_id}     # ユーザーロール変更（Admin のみ）
```

#### プロフィール管理
```
GET    /api/v1/users/me                 # 現在のユーザー情報取得
PUT    /api/v1/users/me                 # ユーザー情報更新
PUT    /api/v1/users/me/password        # パスワード変更
DELETE /api/v1/users/me                 # アカウント削除
```

#### ユーザー管理
```
GET    /api/v1/users/                   # 全ユーザー一覧（Admin のみ）
DELETE /api/v1/users/{user_id}          # ユーザー削除（Admin のみ）
```

### 4. サーバー管理 (`/api/v1/servers`)

#### サーバーCRUD操作
```
POST   /api/v1/servers                  # サーバー作成（Operator/Admin）
GET    /api/v1/servers                  # サーバー一覧（ページネーション）
GET    /api/v1/servers/{server_id}      # サーバー詳細取得
PUT    /api/v1/servers/{server_id}      # サーバー設定更新
DELETE /api/v1/servers/{server_id}      # サーバー削除
```

#### サーバー制御
```
POST   /api/v1/servers/{server_id}/start    # サーバー開始
POST   /api/v1/servers/{server_id}/stop     # サーバー停止
POST   /api/v1/servers/{server_id}/restart  # サーバー再起動
GET    /api/v1/servers/{server_id}/status   # サーバーステータス取得
POST   /api/v1/servers/{server_id}/command  # サーバーコマンド送信
GET    /api/v1/servers/{server_id}/logs     # サーバーログ取得
```

#### ユーティリティ・管理
```
GET    /api/v1/servers/versions/supported           # サポート対象MCバージョン一覧
GET    /api/v1/servers/cache/stats                 # JARキャッシュ統計（Admin のみ）
POST   /api/v1/servers/cache/cleanup               # キャッシュクリーンアップ（Admin のみ）
GET    /api/v1/servers/java/compatibility          # Java互換性情報
GET    /api/v1/servers/java/validate/{mc_version}  # MCバージョンのJava互換性検証
```

#### インポート・エクスポート
```
GET    /api/v1/servers/{server_id}/export  # サーバーエクスポート（ZIP）
POST   /api/v1/servers/import              # サーバーインポート（Operator/Admin）
```

### 5. グループ管理 (`/api/v1/groups`)

#### グループCRUD
```
POST   /api/v1/groups                   # グループ作成（Operator/Admin）
GET    /api/v1/groups                   # グループ一覧（フィルタリング）
GET    /api/v1/groups/{group_id}        # グループ詳細取得
PUT    /api/v1/groups/{group_id}        # グループ更新
DELETE /api/v1/groups/{group_id}        # グループ削除
```

#### プレイヤー管理
```
POST   /api/v1/groups/{group_id}/players             # プレイヤー追加
DELETE /api/v1/groups/{group_id}/players/{player_uuid}  # プレイヤー削除
```

#### サーバーアタッチメント
```
POST   /api/v1/groups/{group_id}/servers           # グループをサーバーにアタッチ
DELETE /api/v1/groups/{group_id}/servers/{server_id}  # サーバーからデタッチ
GET    /api/v1/groups/{group_id}/servers           # アタッチされたサーバー一覧
GET    /api/v1/groups/servers/{server_id}          # サーバー上のグループ一覧
```

### 6. バックアップ管理 (`/api/v1/backups`)

#### バックアップCRUD
```
POST   /api/v1/backups/servers/{server_id}/backups        # バックアップ作成（Operator/Admin）
POST   /api/v1/backups/servers/{server_id}/backups/upload # バックアップアップロード（Operator/Admin）
GET    /api/v1/backups/servers/{server_id}/backups        # サーバーバックアップ一覧
GET    /api/v1/backups/backups                            # 全バックアップ一覧（Admin のみ）
GET    /api/v1/backups/backups/{backup_id}                # バックアップ詳細取得
DELETE /api/v1/backups/backups/{backup_id}                # バックアップ削除（Operator/Admin）
```

#### バックアップ操作
```
POST   /api/v1/backups/backups/{backup_id}/restore                    # バックアップ復元（Operator/Admin）
GET    /api/v1/backups/backups/{backup_id}/download                   # バックアップダウンロード
```

#### 統計・スケジューリング
```
GET    /api/v1/backups/servers/{server_id}/backups/statistics  # サーバーバックアップ統計
GET    /api/v1/backups/backups/statistics                      # グローバルバックアップ統計（Admin のみ）
POST   /api/v1/backups/backups/scheduled                       # スケジュールバックアップ作成（Admin のみ）
```

### 7. ファイル管理 (`/api/v1/files`)

#### ファイル操作
```
GET    /api/v1/files/servers/{server_id}/files[/{path:path}]           # ファイル・ディレクトリ一覧
GET    /api/v1/files/servers/{server_id}/files/{file_path:path}/read   # ファイル読み取り
PUT    /api/v1/files/servers/{server_id}/files/{file_path:path}        # ファイル書き込み（Operator/Admin）
DELETE /api/v1/files/servers/{server_id}/files/{file_path:path}        # ファイル削除（Operator/Admin）
PATCH  /api/v1/files/servers/{server_id}/files/{file_path:path}/rename # ファイル名変更（Operator/Admin）
```

#### アップロード・ダウンロード
```
POST   /api/v1/files/servers/{server_id}/files/upload                     # ファイルアップロード（Operator/Admin）
GET    /api/v1/files/servers/{server_id}/files/{file_path:path}/download   # ファイルダウンロード
```

#### ディレクトリ・検索
```
POST   /api/v1/files/servers/{server_id}/files/{directory_path:path}/directories  # ディレクトリ作成（Operator/Admin）
POST   /api/v1/files/servers/{server_id}/files/search                             # ファイル検索
```

#### ファイル履歴管理
```
GET    /api/v1/files/servers/{server_id}/files/{file_path:path}/history           # ファイル編集履歴
GET    /api/v1/files/servers/{server_id}/files/{file_path:path}/history/{version} # バージョン内容取得
POST   /api/v1/files/servers/{server_id}/files/{file_path:path}/history/{version}/restore  # バージョン復元（Operator/Admin）
DELETE /api/v1/files/servers/{server_id}/files/{file_path:path}/history/{version}  # バージョン削除（Admin のみ）
GET    /api/v1/files/servers/{server_id}/files/history/statistics                 # ファイル履歴統計
```

### 8. WebSocket (`/api/v1/ws`)

#### リアルタイム通信
```
WebSocket  /api/v1/ws/servers/{server_id}/logs     # サーバーログストリーミング
WebSocket  /api/v1/ws/servers/{server_id}/status   # サーバーステータス更新
WebSocket  /api/v1/ws/notifications                # システム通知
```

### 9. 監査ログ (`/api/v1/audit`)

#### 監査ログ管理
```
GET    /api/v1/audit/logs                      # 監査ログ一覧（フィルタリング、ページネーション）
GET    /api/v1/audit/security-alerts          # セキュリティアラート（Admin のみ）
GET    /api/v1/audit/user/{user_id}/activity  # ユーザーアクティビティ
GET    /api/v1/audit/statistics               # 監査統計（Admin のみ）
```

## 認証・認可

### JWTトークンシステム
- **アクセストークン**: 短期間（30分）
- **リフレッシュトークン**: 長期間（7日）
- **トークンブラックリスト**: ログアウト対応
- **Bearerトークン**: 保護されたエンドポイントでは`Authorization`ヘッダーが必要

### ロールベースアクセス制御（RBAC）

#### ロール階層
1. **admin** - システム全体へのアクセス
2. **operator** - サーバー、グループ、バックアップ、ファイル管理
3. **user** - 所有リソースへの読み取り専用アクセス

#### 権限マトリックス

| 操作 | User | Operator | Admin |
|------|------|----------|-------|
| 自分のサーバー表示 | ✅ | ✅ | ✅ |
| サーバー作成・変更 | ❌ | ✅ | ✅ |
| サーバー制御（開始・停止） | ❌ | ✅ | ✅ |
| サーバーコマンド送信 | ❌ | ✅ | ✅ |
| グループ作成・管理 | ❌ | ✅ | ✅ |
| バックアップ作成・復元 | ❌ | ✅ | ✅ |
| ファイル変更 | ❌ | ✅ | ✅ |
| ユーザー管理 | ❌ | ❌ | ✅ |
| システム管理 | ❌ | ❌ | ✅ |
| 監査ログ表示（全体） | ❌ | ❌ | ✅ |

### リソース所有権
- ユーザーは自分が所有するリソースまたはアクセス権を付与されたリソースのみアクセス可能
- オペレーターは全サーバー・グループ・バックアップにアクセス可能
- 管理者は無制限アクセス

## 主要機能

### セキュリティ機能
- リフレッシュトークン付きJWT認証
- 包括的監査ログ
- ロールベースアクセス制御
- サーバーコマンド完全ログ
- IPアドレスとユーザーエージェント追跡

### リアルタイム機能
- WebSocketベースサーバーログストリーミング
- リアルタイムサーバーステータス更新
- システム全体通知
- ライブコンソールセッション

### 高度な機能
- ファイル編集履歴とバージョン管理
- Javaバージョン互換性管理
- サーバーインポート・エクスポート機能
- ファイル検索とコンテンツインデックス

### 監視・分析
- パフォーマンスメトリクスエンドポイント
- バックアップ統計と分析
- ファイル操作統計
- ユーザーアクティビティ追跡
- セキュリティアラートシステム

## エラーハンドリング

### 標準HTTPステータスコード
- `200` - 成功
- `201` - 作成済み
- `204` - コンテンツなし
- `400` - 不正なリクエスト
- `401` - 認証されていない
- `403` - 禁止されている
- `404` - 見つからない
- `409` - 競合
- `422` - バリデーションエラー
- `500` - 内部サーバーエラー

### エラーレスポンス形式
```json
{
  "detail": "エラーメッセージ",
  "error_code": "具体的エラーコード",
  "field_errors": {
    "field_name": ["フィールド固有エラー"]
  }
}
```

## ページネーション・フィルタリング

### 標準ページネーションパラメータ
- `skip` - スキップするレコード数（デフォルト: 0）
- `limit` - 返却する最大レコード数（デフォルト: 10、最大: 100）

### 共通フィルターパラメータ
- `search` - 関連フィールドでのテキスト検索
- `sort_by` - ソートフィールド
- `sort_order` - `asc` または `desc`
- `created_after` / `created_before` - 日付範囲フィルタリング

## レート制限

### デフォルト制限
- **一般API**: ユーザーあたり1時間に1000リクエスト
- **認証**: IPあたり1分間に10リクエスト
- **サーバーコマンド**: ユーザーあたり1分間に60リクエスト
- **ファイル操作**: ユーザーあたり1分間に100リクエスト

この合理化されたAPIは、コアユースケースをカバーする複数のMinecraftサーバー管理の必須機能を提供し、企業グレードのセキュリティ、監視、管理機能を備えています。