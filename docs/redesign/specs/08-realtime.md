# 仕様書: リアルタイム通信 (WebSocket)

## 認証方式

WebSocket は HTTP ヘッダーにトークンを乗せられないため、クエリパラメータで JWT を渡す。

```
ws://host/servers/{server_id}/logs?token=<JWT>
```

---

## WebSocket エンドポイント

### WS /servers/{server_id}/logs — サーバーログ/コマンドストリーム

**概要:** サーバーのコンソールログをリアルタイム配信し、コマンド送信も受け付ける。

**クライアント → サーバー メッセージ:**

| type | 追加フィールド | 説明 |
|------|--------------|------|
| ping | - | 接続維持 |
| send_command | command: string | コンソールコマンド送信 (admin/operator のみ) |
| request_status | - | 現在のサーバー状態をリクエスト |

**サーバー → クライアント メッセージ:**

| type | フィールド | 説明 |
|------|----------|------|
| initial_status | status オブジェクト | 接続時に送信される初期状態 |
| server_log | log_line, log_type | ログ行の配信 |
| server_status | status オブジェクト | 状態変化の通知 |
| notification | 通知オブジェクト | システム通知 |
| pong | - | ping への応答 |

**log_type の種類:** error / warning / info / debug / player_join / player_leave / chat / other

**接続フロー:**
1. JWT を検証してユーザー取得
2. サーバーの存在確認とアクセス権チェック
3. 接続を ConnectionManager に登録
4. 初期サーバー状態を送信
5. ログストリームタスクを開始 (同サーバーに接続者がいない場合のみ新規起動)
6. クライアントからのメッセージを処理:
   - ping → pong
   - send_command → admin/operator の場合のみ RCON/stdin でコマンド実行
   - request_status → 現在の状態を返信
7. 切断時: ConnectionManager から削除、接続者が 0 になればログストリームを停止

**ログストリームの仕組み:**
- サーバーの `latest.log` をテールフォロー形式で読み続ける
- ログ内容からタイプ (error / warning / player_join 等) を判定
- 同じサーバーに接続している全クライアントにブロードキャスト

---

### WS /servers/{server_id}/status — サーバー状態ストリーム

**概要:** サーバー状態の変化をリアルタイム配信する。

ログストリームエンドポイントと同じ仕組みだが、状態通知に特化。

---

### WS /notifications — システム通知ストリーム

**概要:** ユーザー向けのシステム通知を受け取るチャネル。

**クライアント → サーバー:**

| type | 説明 |
|------|------|
| ping | 接続維持 |

**サーバー → クライアント:**

| type | フィールド | 説明 |
|------|----------|------|
| welcome | message, timestamp | 接続時に送信 |
| pong | timestamp | ping への応答 |

---

## 状態監視の仕組み

バックグラウンドで 5 秒ごとに全稼働サーバーの状態を確認し、接続クライアントにブロードキャストする。

**status オブジェクトの構造:**
```json
{
  "server_id": 1,
  "status": "running",
  "process_info": {
    "pid": 12345,
    "started_at": "ISO8601",
    "uptime_seconds": 300.5
  }
}
```

## ConnectionManager の仕組み

```
active_connections: Map<server_id, Set<WebSocket>>
  - サーバーごとの接続中 WebSocket を管理

user_connections: Map<WebSocket, User>
  - WebSocket とユーザーの紐付け

server_log_tasks: Map<server_id, asyncio.Task>
  - サーバーごとのログストリームタスク
```

**接続時:** 同サーバーに初めて接続する場合のみログタスクを起動
**切断時:** 同サーバーの接続者が 0 になったらログタスクを停止

## セキュリティ要件

- JWT トークンの有効性を接続時に必ず確認
- サーバーへのアクセス権を確認 (404 または権限エラー)
- コマンド送信は admin / operator ロールのみ許可
- 送信されたコマンドは監査ログに記録
