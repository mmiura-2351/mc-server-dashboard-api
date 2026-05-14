# Test Baseline (Issue #166)

Issue #166 (C-1) で計測した現状のテストスイートのベースライン。Issue #151 (テスト設計見直し) 配下の改善目標を立てる材料として利用する。

- **計測日**: 2026-05-14
- **対象ブランチ**: `feature/issue-166-test-baseline` (master ベース)
- **環境**: Python 3.13.3, pytest 8.4.1, pytest-xdist (`-n auto --dist loadscope` を `pytest.ini` で適用)

## 1. テスト規模

| レイヤ | テスト数 | コード行数 |
|---|---:|---:|
| `tests/unit/` | 1,142 | (内訳省略) |
| `tests/integration/` | 310 | |
| `tests/infrastructure/` | 41 | |
| `tests/test_security.py` (top-level) | 44 | |
| **合計** | **1,537** | **34,115** |

参考: アプリ本体は 25,778 行。**テストコード量はアプリの 1.32 倍**。

## 2. 実行時間

### 2.1 レイヤ単独実行 (xdist `-n auto` 有効)

| レイヤ | pytest 経過 | 結果 |
|---|---:|---|
| `tests/unit/` | **78.83s** | 1,141 passed, 1 skipped |
| `tests/integration/` | **78.72s** | 282 passed, 5 failed, 35 errors |
| `tests/infrastructure/` | **2.96s** | 38 passed, 3 errors |
| `tests/test_security.py` | **0.05s** | 44 passed |
| (合計の素朴和) | 約 160s | |

### 2.2 全体実行 + カバレッジ計測 (xdist が無効化される)

| 計測 | 値 |
|---|---:|
| 経過時間 | **204.29s** (3:24) |
| 結果 | 1,091 passed, 1 skipped, 445 errors |

**観察**:
- レイヤ別実行時には 0〜35 件だったエラーが、全体+coverage 実行では **445 件まで急増**
- `coverage run -m pytest` 配下では pytest-xdist がワーカー分散せず、ジョブが直列で走るためテスト間干渉 (DB 状態等) が発生していると推定される
- 改善方向: `coverage run --parallel-mode -m pytest && coverage combine` への切り替え、または `pytest-cov` 経由 (`--cov`) で xdist と両立させる

## 3. スローテスト

### 3.1 `tests/unit/` Top 10

| 経過 | フェーズ | テスト |
|---:|---|---|
| 7.75s | setup | `tests/unit/models/test_backup_schedule_models.py::TestBackupScheduleModel::test_create_backup_schedule_success` |
| 1.44s | call | `tests/unit/services/test_user_service.py::TestUserService::test_register_first_user_as_admin` |
| 1.00s | call | `tests/unit/services/test_server_service.py::TestServerService::test_wait_for_server_status_eventual_success` |
| 1.00s | teardown | `tests/unit/servers/test_service.py::TestServerJarServiceExtended::test_get_server_jar_unsupported_version` |
| 1.00s | call | `tests/unit/services/test_server_service.py::TestServerService::test_wait_for_server_status_timeout` |
| 1.00s | call | `tests/unit/servers/test_control_router.py::TestServerControlRouter::test_restart_server_success` |
| 0.88s | call | `tests/unit/services/test_version_manager.py::TestMinecraftVersionManagerMissingCoverage::test_get_forge_versions_success` |
| 0.52s | teardown | `tests/unit/servers/test_service.py::TestServerJarServiceExtended::test_get_server_jar_exception_handling` |
| 0.51s | setup | `tests/unit/services/test_authorization_service.py::TestAuthorizationServiceDeletionPermissions::test_can_delete_backup_non_owner_cannot_delete` |
| 0.51s | setup | `tests/unit/services/test_authorization_service.py::TestAuthorizationServiceRoleHierarchy::test_role_hierarchy_admin_highest` |

**注目**:
- `test_create_backup_schedule_success` の setup が **7.75 秒** と突出 — fixture チューニング余地
- `wait_for_server_status_*` 系は 1 秒の sleep/poll を含んでいる可能性が高い → mock 化で短縮可
- authorization_service の setup が 0.4〜0.5s 範囲に多数 → 共通 fixture 化が効きそう

### 3.2 `tests/integration/` Top 10

| 経過 | フェーズ | テスト |
|---:|---|---|
| 6.01s | call | `test_minecraft_server_monitoring.py::TestMinecraftServerMonitoringIntegration::test_monitor_server_stable_process` |
| 2.00s | call | `test_minecraft_server_monitoring.py::TestMinecraftServerMonitoringIntegration::test_read_server_logs_complete_workflow` |
| 1.31s | call | `test_minecraft_server_lifecycle.py::TestMinecraftServerLifecycleIntegration::test_server_startup_process_immediate_exit` |
| 1.16s | setup | `api/test_auth_router.py::TestAuthRouter::test_login_invalid_username` |
| 1.01s | call | `test_minecraft_server_monitoring.py::TestMinecraftServerMonitoringIntegration::test_read_server_logs_queue_overflow_handling` |
| 1.00s | call | `test_minecraft_server_monitoring.py::TestMinecraftServerMonitoringIntegration::test_read_server_logs_exception_handling` |
| 0.93s | setup | `api/test_auth_router.py::TestAuthRouter::test_login_success` |
| 0.81s | call | `test_minecraft_server_lifecycle.py::TestMinecraftServerLifecycleIntegration::test_server_startup_complete_workflow_success` |
| 0.50s | call | `test_minecraft_server_monitoring.py::TestMinecraftServerMonitoringIntegration::test_monitor_server_crash_detection` |
| 0.50s | call | `test_minecraft_server_monitoring.py::TestMinecraftServerMonitoringIntegration::test_monitor_server_normal_termination` |

**注目**:
- 上位は **minecraft_server_monitoring / lifecycle** に集中。実プロセス起動を伴うため、別レイヤ (infrastructure) への移動候補
- `test_auth_router` の setup が 1s 前後と重い → 共通 token 取得 fixture を `session` スコープで持てば短縮

### 3.3 `tests/infrastructure/` Top 5

| 経過 | フェーズ | テスト |
|---:|---|---|
| 1.44s | setup | `test_parallel_execution_isolation.py::test_database_file_creation` |
| 0.71s | setup | `test_parallel_execution_isolation.py::test_test_isolation_different_data` |
| 0.22s | setup | `test_parallel_execution_isolation.py::test_test_isolation_simple_data` |
| 0.01s | call | `test_templates_router_infrastructure.py::TestTemplatesRouterAPI::test_templates_endpoints_require_auth` |
| 0.01s | call | `test_performance_monitoring.py::TestPerformanceMonitoringMiddleware::test_middleware_adds_headers` |

## 4. カバレッジ (statement-based)

### 4.1 ドメイン別

| Domain | Stmts | Miss | Coverage |
|---|---:|---:|---:|
| `app/types.py` | 14 | 0 | **100.00%** |
| `app/websockets/` | 46 | 0 | **100.00%** |
| `app/users/` | 117 | 25 | 78.63% |
| `app/core/` | 770 | 186 | 75.84% |
| `app/main.py` | 194 | 59 | 69.59% |
| `app/versions/` | 770 | 256 | 66.75% |
| `app/servers/` | 1,167 | 403 | 65.47% |
| `app/files/` | 267 | 97 | 63.67% |
| `app/services/` | 4,972 | 1,854 | 62.71% |
| `app/middleware/` | 403 | 167 | 58.56% |
| `app/groups/` | 307 | 154 | 49.84% |
| `app/templates/` | 218 | 113 | 48.17% |
| `app/backups/` | 511 | 280 | 45.21% |
| `app/audit/` | 238 | 133 | 44.12% |
| `app/auth/` | 128 | 84 | 34.38% |
| **TOTAL (statement)** | **10,122** | **3,811** | **62.35%** |
| **TOTAL (statement + branch)** | — | — | **59.78%** |

### 4.2 低カバレッジファイル Top 15

| Coverage | File | Missing |
|---:|---|---|
| 0.00% | `app/core/visibility_router.py` | 125 / 125 |
| 0.00% | `app/core/visibility_schemas.py` | 45 / 45 |
| 0.00% | `app/services/visibility_migration_service.py` | 88 / 88 |
| 9.40% | `app/services/group_service.py` | 297 / 338 |
| 10.94% | `app/services/visibility_service.py` | 111 / 132 |
| 15.03% | `app/services/user.py` | 90 / 113 |
| 16.08% | `app/services/backup_scheduler.py` | 121 / 153 |
| 16.52% | `app/backups/router.py` | 160 / 198 |
| 17.39% | `app/servers/routers/import_export.py` | 86 / 110 |
| 18.52% | `app/backups/scheduler_router.py` | 86 / 111 |
| 22.00% | `app/auth/auth.py` | 33 / 44 |
| 22.00% | `app/versions/service.py` | 99 / 132 |
| 22.31% | `app/templates/router.py` | 80 / 107 |
| 22.40% | `app/versions/repository.py` | 81 / 109 |
| 24.82% | `app/middleware/database_monitoring.py` | 86 / 117 |

**注目**:
- 0% の 3 ファイルは **visibility 機能** に集中 — Issue #149 (リファクタ) の前にテスト追加すべきか、削除候補か要判断
- `group_service.py` (9.4%) と `visibility_service.py` (10.9%) は Issue #149 の分割対象でもあり、テスト整備とリファクをセットで進めるべき
- 既存の Issue #78 (Groups/Templates のテストカバレッジ改善) と整合する

## 5. その他の所見

### 5.1 テスト失敗・エラー

| 計測条件 | passed | failed | errors |
|---|---:|---:|---:|
| 各レイヤ単独 (合計) | 1,505 | 5 | 43 |
| 全体 + coverage | 1,091 | 0 | **445** |

- **xdist 単独実行時は 43 件のエラー**: 主に `tests/integration/api/` (fixture 起因の疑い) と `tests/infrastructure/test_parallel_execution_isolation.py`
- **coverage 実行時はエラー +400 件以上**: 並列実行が無効化されることでテスト間干渉 (DB / グローバル状態) が顕在化
- 既存の Issue #65 (warnings 削減) と関連

### 5.2 推定される重複・整理候補

- `tests/integration/test_minecraft_server_*.py` 系列が 5 ファイル → 同一機能の細分化テストが集中。統合候補
- `tests/unit/services/test_authorization_service.py` と `test_authorization_service_phase2.py` の分離理由が不明 → マージ候補
- `tests/unit/servers/` と `tests/unit/servers/routers/` の境界が曖昧

(本項は目視観察。詳細な重複検出は別途実施)

### 5.3 設定面の改善余地

| 項目 | 現状 | 案 |
|---|---|---|
| `coverage run -m pytest` | xdist 無効化 → テスト間干渉 | `coverage run --parallel-mode` + `coverage combine`、または `pytest-cov` 採用 |
| `pre-commit` での実行範囲 | フルスイート (3〜5分) | unit only + `slow` マーカー除外。integration は CI のみ (→ Issue #171 / C-6) |
| `pytest.ini` の `addopts` | `-q --disable-warnings` | warning 抑止は `filterwarnings` に集約、`-q` は維持 |
| カバレッジ閾値 | 設定なし | 全体 60% / 重要ドメイン 80% などの段階目標を設定 (→ Issue #167 / C-2) |

## 6. 次のステップ (Issue #151 配下)

| Issue | 改善目標 (本ベースラインから) |
|---|---|
| #167 (C-2: テスト階層ポリシー) | unit / integration / infrastructure の判別基準を明文化。slow tests の移動・マーカー化方針を策定 |
| #168 (C-3: フィクスチャ整理) | authorization_service 周辺の setup 0.4〜0.5s × 多数 を共通化で短縮 |
| #169 (C-4: スローテスト並列化/マーカー) | minecraft_server_monitoring / lifecycle 系を `@pytest.mark.slow` 化または infrastructure へ移動 |
| #170 (C-5: リファクと連動した再配置) | Issue #149 のサービス分割に追従。低カバレッジ ファイル (`group_service.py` 等) は分割と同時にテスト充実 |
| #171 (C-6: pre-commit 範囲再検討) | pre-commit は unit のみ。integration は pre-push / CI。フルカバレッジは nightly |
| #149 系 (リファクタ) | カバレッジ 0% の visibility 系は方針決定 (テスト追加 or 削除) を先に行う |

## 付録: 計測コマンド

```bash
# レイヤ別 (基準実行、xdist 有効)
uv run pytest tests/unit --durations=20 -q
uv run pytest tests/integration --durations=20 -q
uv run pytest tests/infrastructure --durations=10 -q
uv run pytest tests/test_security.py --durations=20 -q

# 全体 + カバレッジ
uv run coverage run -m pytest --durations=20 -q
uv run coverage report

# テスト数収集
uv run pytest --collect-only -q
```
