# 仕様書: リアルタイム通信 (WebSocket)

## 設計方針

- **Runner 経由のログストリーム。** API Core はファイルシステムを直接読まず、Runner のログストリームインターフェースを購読し、クライアントへ中継する
- **コンソール・ステータス・コマンドを1チャネルに統合。** v1 の `/logs` と `/status` を `/console` に統合し、重複を排除する
- **通知チャネルはジョブ更新を含む。** 非同期ジョブの完了・失敗もリアルタイムで配信する
- **スケーリング考慮。** 初期実装はインプロセスの ConnectionManager で行うが、API Core を水平スケールする場合は pub/sub バックエンド（Redis 等）への置き換えが必要

---

## 認証

WebSocket は HTTP ヘッダーでトークンを送れないため、クエリパラメータで JWT を渡す。

```
wss://host/api/v2/organizations/{org_id}/servers/{server_id}/console?token=<JWT>
```

- 接続時に JWT を検証し、無効なら即座に接続を閉じる (`4001 Unauthorized`)
- JWT の検証は接続時のみ行う。接続確立後にトークンが期限切れになっても切断しない
- クライアントが再接続する場合は `/auth/refresh` で新しいトークンを取得してから接続する

---

## メッセージ形式

すべてのメッセージは JSON。`type` フィールドで種別を識別する。

---

## WebSocket エンドポイント

### WS /api/v2/organizations/{org_id}/servers/{server_id}/console — コンソールストリーム

**概要:** サーバーのコンソールログをリアルタイム配信し、コマンド送信・状態監視も行う統合チャネル。

**必要権限:** `server.read` (接続・ログ受信) / `server.command` (コマンド送信)

---

#### クライアント → サーバー

| type | 追加フィールド | 説明 |
|------|--------------|------|
| `ping` | - | 接続維持 |
| `send_command` | `command: string` | コンソールコマンド送信 (`server.command` 権限必須) |
| `request_status` | - | 現在のサーバー状態をリクエスト |

**`send_command` の制約:**
- `server.command` 権限がない場合は `4003 Forbidden` でメッセージを拒否
- `stop` / `restart` / `shutdown` コマンドは禁止 (ライフサイクル API を使用)
- コマンド実行は RCON 経由 (Runner インターフェース)
- 監査ログに記録

---

#### サーバー → クライアント

| type | フィールド | 説明 |
|------|----------|------|
| `pong` | `timestamp` | ping への応答 |
| `initial_status` | `server` | 接続直後に一度送信される初期状態 |
| `log` | `line`, `log_type`, `timestamp` | ログ行の配信 |
| `status_change` | `server` | サーバー状態変化の通知 |
| `error` | `message` | エラー通知 |

**`log_type` の値:** `error` / `warning` / `info` / `debug` / `player_join` / `player_leave` / `chat` / `other`

**`server` オブジェクト:**
```json
{
  "server_id": "uuid",
  "status": "running | stopped | starting | stopping | ...",
  "runner_type": "docker",
  "runner_instance_id": "abc123",
  "started_at": "ISO8601 | null",
  "uptime_seconds": 300.5
}
```

**接続フロー:**
1. JWT を検証してユーザーと権限を確認
2. サーバーの存在・Organization への所属を確認
3. ConnectionManager に登録
4. `initial_status` を送信
5. Runner のログストリームを購読 (同サーバーへの初回接続時のみ新規購読を開始)
6. クライアントからのメッセージを処理
7. 切断時: ConnectionManager から削除。同サーバーの接続者が 0 になったらログストリーム購読を解除

**ログストリームの仕組み:**
- Runner インターフェースの `stream_logs(runner_instance_id)` を呼び出し、ログ行を非同期で受信
- ログ内容からタイプ (`player_join`, `error` 等) をパターンマッチで判定
- 同サーバーに接続している全クライアントにブロードキャスト

---

### WS /api/v2/notifications — 通知ストリーム

**概要:** ユーザー向けのシステム通知・ジョブ更新をリアルタイムで受け取るチャネル。
Organization に限定せず、そのユーザーに関連するすべての通知を配信する。

**必要権限:** 認証済みユーザー

**接続 URL:**
```
wss://host/api/v2/notifications?token=<JWT>
```

---

#### クライアント → サーバー

| type | 説明 |
|------|------|
| `ping` | 接続維持 |

---

#### サーバー → クライアント

| type | フィールド | 説明 |
|------|----------|------|
| `welcome` | `user_id`, `timestamp` | 接続時に送信 |
| `pong` | `timestamp` | ping への応答 |
| `job_update` | `job` | ジョブ状態変化の通知 |
| `notification` | `title`, `message`, `severity`, `timestamp` | システム通知 |

**`job` オブジェクト:**
```json
{
  "job_id": "uuid",
  "server_id": "uuid",
  "server_name": "string",
  "type": "server_start | server_stop | backup_create | ...",
  "status": "queued | running | succeeded | failed | cancelled",
  "updated_at": "ISO8601"
}
```

**`severity` の値:** `info` / `warning` / `error`

**配信対象のイベント:**
- 自分がトリガーしたジョブの状態変化
- 自分が所属する Organization のサーバーに対するジョブの状態変化
- システム通知 (メンテナンス予告等)

---

## ConnectionManager

```
console_connections: Map<server_id, Set<(WebSocket, User)>>
  - サーバーごとの接続中 WebSocket とユーザーを管理

notification_connections: Map<user_id, Set<WebSocket>>
  - ユーザーごとの通知チャネル接続を管理

runner_log_tasks: Map<server_id, Task>
  - サーバーごとの Runner ログストリーム購読タスク
```

**接続時:** 同サーバーへの初回接続のみ Runner ログストリームの購読タスクを起動
**切断時:** 同サーバーの接続者が 0 になったら購読タスクをキャンセル

**水平スケーリング時の注意:**
初期実装はインプロセスの ConnectionManager で動作する。
API Core を複数インスタンスで動かす場合、接続先インスタンスが異なるとブロードキャストが届かないため、**Redis pub/sub 等の外部 pub/sub バックエンドへの置き換えが必要**になる。

---

## サーバー状態監視

バックグラウンドで定期的に Runner からサーバー状態を取得し、変化があれば `status_change` イベントをブロードキャストする。

- **ポーリング間隔:** 5 秒
- **対象:** `console_connections` に1件以上接続があるサーバーのみ
- **変化検出:** 前回取得した `status` と異なる場合のみ配信 (差分配信)

---

## セキュリティ要件

- JWT の有効性を接続時に必ず検証。無効なら `4001` で切断
- サーバーへのアクセス権を確認。権限なしなら `4003` で切断
- `send_command` は `server.command` 権限を持つユーザーのみ実行可能
- 禁止コマンド (`stop` 等) を送信した場合は `error` メッセージを返しコマンドは実行しない
- 実行されたすべてのコマンドを監査ログに記録

---

## WebSocket クローズコード

| コード | 意味 |
|--------|------|
| `4001` | Unauthorized (JWT 無効・期限切れ) |
| `4003` | Forbidden (権限不足) |
| `4004` | Server not found |

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| `send_command.command` | 1-500 文字、禁止コマンドを含まない |
