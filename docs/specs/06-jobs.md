# 仕様書: ジョブ管理 (非同期タスク)

## 設計方針

- **すべてのライフサイクル操作は Job として永続化。** サーバー作成/起動/停止/削除・バックアップ作成/復元は即時レスポンスを返さず、202 + job_id を返す
- **at-least-once 実行。** ジョブは少なくとも1回実行されることを保証する。ジョブ実装は冪等に設計する
- **Runner とのデカップリング。** ジョブワーカーがキューからジョブを取り出し、Runner インターフェース経由で操作を実行する。API Core は直接 Runner を呼ばない
- **状態は DB に永続化。** ワーカー再起動をまたいでジョブ状態を引き継ぐ
- **Organization スコープ。** ジョブはサーバーに属し、同じ Organization のメンバーのみ参照可能

---

## データモデル

### Job

| フィールド | 型 | 制約 | デフォルト | 説明 |
|-----------|-----|------|-----------|------|
| id | UUID | PK | gen_random_uuid() | - |
| server_id | UUID | FK(servers.id), NOT NULL | - | 対象サーバー |
| type | enum | NOT NULL | - | 下記参照 |
| status | enum | NOT NULL | queued | 下記参照 |
| triggered_by_user_id | UUID | FK(users.id), ON DELETE SET NULL | NULL | トリガーしたユーザー (スケジュール実行時は NULL) |
| payload | JSON | - | {} | ジョブ実行に必要なパラメータ |
| error_message | text | - | NULL | 失敗時のエラー内容 |
| retry_count | int | NOT NULL | 0 | 現在のリトライ回数 |
| max_retries | int | NOT NULL | 0 | 最大自動リトライ回数 (0 = 自動リトライなし) |
| started_at | datetime(tz) | - | NULL | ワーカーが処理開始した日時 |
| completed_at | datetime(tz) | - | NULL | 完了（成功/失敗/キャンセル）日時 |
| created_at | datetime(tz) | NOT NULL | now() | ジョブ作成（キューへの投入）日時 |

---

## Job type 一覧

| type | トリガーとなる操作 | 関連仕様 |
|------|-----------------|---------|
| `server_create` | POST .../servers | specs/03-servers.md |
| `server_start` | POST .../servers/{id}/start | specs/03-servers.md |
| `server_stop` | POST .../servers/{id}/stop | specs/03-servers.md |
| `server_restart` | POST .../servers/{id}/restart | specs/03-servers.md |
| `server_delete` | DELETE .../servers/{id} | specs/03-servers.md |
| `backup_create` | POST .../backups | specs/05-backups.md |
| `backup_restore` | POST .../backups/{id}/restore | specs/05-backups.md |

---

## Job status 遷移

```
    ┌─────────┐
    │  queued │ ← キューへの投入直後
    └────┬────┘
         │ ワーカーが取り出す
         ▼
    ┌─────────┐
    │ running │ ← Runner に操作を委譲中
    └──┬──┬───┘
       │  │
成功   │  │ 失敗
       ▼  ▼
┌──────────┐  ┌────────┐
│succeeded │  │ failed │ ← error_message に詳細を記録
└──────────┘  └────────┘
       ↑ (手動リトライ時に新ジョブとして再投入)

queued 状態のみ cancelled に遷移可能:
    queued → cancelled (POST .../jobs/{id}/cancel)
```

| status | 意味 |
|--------|------|
| `queued` | ワーカーへの取り出し待ち |
| `running` | ワーカーが処理中 |
| `succeeded` | 正常完了 |
| `failed` | エラーで終了 |
| `cancelled` | キャンセル済み (queued 状態のみ可能) |

---

## JobResponse

```json
{
  "job_id": "uuid",
  "server_id": "uuid",
  "type": "server_create | server_start | server_stop | server_restart | server_delete | backup_create | backup_restore",
  "status": "queued | running | succeeded | failed | cancelled",
  "triggered_by_username": "string | null",
  "error_message": "string | null",
  "retry_count": 0,
  "created_at": "ISO8601",
  "started_at": "ISO8601 | null",
  "completed_at": "ISO8601 | null"
}
```

---

## 実行保証と冪等性

**at-least-once 保証:**
- ジョブは DB に `status=queued` で永続化された後にキューへ送信する
- ワーカー起動時は `status=running` のまま完了していないジョブを検出して再実行する
- ワーカーの二重起動等で同じジョブが複数実行される可能性があるため、各ジョブの実装は冪等に設計する

**冪等性の実現方法（例）:**
- `server_start`: Runner に起動を依頼する前に Runner の現在状態を確認し、すでに起動中なら skip
- `backup_create`: `job_id` をストレージキーの一部に含め、同じジョブが再実行されても同じキーに書き込む（上書き）

---

## タイムアウトポリシー

| job type | タイムアウト | タイムアウト時の挙動 |
|----------|------------|------------------|
| `server_create` | 300 秒 | `status=failed`、サーバー `status=error`。Runner 側の中途生成リソースはクリーンアップしない。ユーザーが DELETE エンドポイントで明示的に削除する |
| `server_start` | 90 秒 | `status=failed`、サーバー `status=error` |
| `server_stop` | 60 秒 | 強制終了後 `status=succeeded`、サーバー `status=stopped` |
| `server_restart` | 150 秒 | `status=failed`、サーバー `status=error` |
| `server_delete` | 120 秒 | `status=failed`、サーバー `status=error` |
| `backup_create` | 3600 秒 | `status=failed`、バックアップ `status=failed` |
| `backup_restore` | 3600 秒 | `status=failed`、サーバー `status=error` |

---

## リトライ方針

**自動リトライ:** デフォルト `max_retries=0`（自動リトライなし）。ライフサイクル操作は副作用が大きいため、自動リトライは慎重に設定する。

**手動リトライ:** `status=failed` のジョブに対して POST .../jobs/{id}/retry を実行すると、**新しい Job レコード** を `status=queued` で作成する（元ジョブは `failed` のまま保持）。リトライ可能な状態は `specs/03-servers.md` の状態遷移バリデーションに従う。

---

## ジョブキュー

**実装:** DB テーブルをジョブキューとして使用する（MVP）。

- ワーカーは `status=queued` のジョブを作成日時昇順で取り出す
- `SELECT ... FOR UPDATE SKIP LOCKED` で複数ワーカーの競合を防ぐ
- フェーズ 2 以降では Redis / NATS JetStream 等の専用キューへの移行を検討する

**並列実行の制約:**
- 同一サーバーに対するジョブは直列に実行する（並列実行しない）
- ワーカーはジョブ取り出し時に同サーバーの `status=running` ジョブが存在しないことを確認する

---

## バリデーション一覧

| 項目 | ルール |
|------|--------|
| cancel 操作 | `status=queued` のジョブのみ |
| retry 操作 | `status=failed` のジョブのみ |
