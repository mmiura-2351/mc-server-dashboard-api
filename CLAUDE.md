# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Standard Development Rules

### Rule 1: New Rule Addition Process
**Continuously improve project standards through rule documentation.**

When receiving instructions from users that appear to require ongoing compliance (not just one-time implementation):

1. Ask: "Should I make this a standard rule?"
2. If YES response is received, add it to CLAUDE.md as an additional rule
3. Apply it as a standard rule for all future interactions

### Rule 2: Task Completion and CI Verification
**Always verify CI passes and commit changes after completing any task.**

When completing any significant task or feature implementation:
1. **CI Verification**: Ensure all tests pass before committing
2. **Code Quality**: Run lint and format checks
3. **Commit Changes**: Create meaningful commit messages with proper documentation

### Rule 3: Test Code Development Process
**Follow systematic approach for test coverage improvement.**

When creating test coverage for services or components:
1. Analyze the implementation thoroughly — identify uncovered lines, error paths, and edge cases
2. Create comprehensive test cases targeting specific uncovered areas
3. Iterate until coverage target is met

### Rule 4: Code Review Issue Creation
**Create GitHub Issues for improvements, bugs, and missing features found during code reviews.**

When reviewing source code and identifying areas for improvement:
1. Create GitHub Issues for any bugs, improvements, or missing features discovered
2. Use appropriate labels and include relevant code references, file paths, and line numbers

### Rule 5: Standard Issue Resolution Process
**Follow systematic approach when fixing GitHub Issues.**

1. **Create Issue Branch**: Pattern `fix/issue-{number}-{brief-description}` or `feature/issue-{number}-{brief-description}`
2. **Analyze Issue Details**: Thoroughly understand requirements and perform necessary analysis
3. **Create Sub-Issues**: If needed, break down complex problems
4. **Implement Solution**: Following project standards
5. **Verify and Create PR**: Confirm resolution and create a pull request

### Rule 6: Test Execution Guidelines
**Be mindful of test execution performance and timeouts.**

Pre-commit hooks run the complete test suite. For manual full-suite runs, extend timeout explicitly.

### Rule 7: Issue Resolution Completion Process
**Always close resolved Issues with proper documentation and status updates.**

1. Verify all issue requirements are fully addressed
2. Update relevant documentation if needed
3. Close with a summary of changes and references to related PRs

### Rule 8: Git/GitHub Workflow Standards
**Follow standardized Git and GitHub practices.**

- Branch naming: `fix/issue-{number}-{description}` or `feature/issue-{number}-{description}`
- PR titles: clear and descriptive; always link related issues with "Resolves #X"
- Keep feature branches updated with latest master changes

### Rule 9: Pull Request Review Process
**Conduct thorough code reviews.**

Use `gh pr view` and `gh pr review`. Review code quality, functionality, tests, documentation, and security. Only approve PRs that meet all quality standards.

### Rule 10: Pull Request Merge Strategy
**Use squash merge as the default merge strategy.**

```
gh pr merge <number> --squash
```

Always delete the feature branch after merge and ensure linked issues are closed.

---

## V2 再設計ドキュメント

作業対象は `docs/redesign/` の Markdown ファイルのみ。実装コードはない。

### ドキュメント構成

```
docs/redesign/
├── 01-current-issues.md          # v1 の設計破綻の分析
├── 02-requirements.md            # v2 機能/非機能要件 (FR-O-*, FR-S-*, NFR-*)
├── 03-architecture-direction.md  # アーキテクチャ方針
├── 04-feature-list.md            # v1 機能一覧と v2 での扱い
└── specs/
    ├── 01-auth-users.md          # 認証 / Organization / ユーザー管理
    ├── 02-groups.md              # プレイヤーグループ (Minecraft OP/whitelist)
    ├── 03-servers.md             # サーバー管理・制御
    ├── 04-versions.md            # Minecraft バージョン管理
    ├── 05-backups.md             # バックアップ管理 / スケジューラー
    ├── 06-jobs.md                # ジョブ管理 (非同期タスク共通仕様)
    ├── 07-files.md               # ファイル管理 / 編集履歴
    ├── 08-realtime.md            # リアルタイム通信 (WebSocket)
    └── 09-audit.md               # 監査ログ
```

### 決定済み設計方針 (再議論しない)

| 決定事項 | 内容 |
|---------|------|
| **Organization モデル** | リソース分離は Organization (1 層) のみ。Tenant + Workspace の 2 層は採用しない |
| **非同期ジョブ** | サーバー起動/停止/作成/削除・バックアップ作成/復元はすべて `202 + job_id` を返す。同期レスポンスにしない |
| **Runner 抽象化** | API Core はファイルシステムに直接アクセスしない。すべての操作は Runner インターフェース経由 (`host` / `docker` / `podman`) |
| **設定の責務分離** | DB はインフラ設定 (memory/cpu/disk) のみ。`server.properties` 等ゲーム設定はファイルが唯一の真実の源 |
| **Groups の定義** | Groups = Minecraft プレイヤーの集合 (OP/whitelist 管理)。ダッシュボードユーザーのグループではない |
| **テンプレート機能** | **v2 廃止。** バックアップ復元で代替する。specs に追加しない |
| **可視性制御** | **v2 廃止。** Organization メンバーシップがアクセス制御を担う |
| **JWT の sub** | `user_id` (UUID)。username 変更によるトークン再発行問題を排除するため |
| **リフレッシュトークン** | デバイス/セッション単位の Refresh Token Rotation。グローバル全失効はしない |
| **多言語対応** | 対象外。単一言語で実装する |
| **MVP Runner** | Docker/Podman が主ターゲット。ホスト Runner はオプション |
| **Org 削除条件** | サーバーが残っている場合は削除不可（誤削除防止）。カスケード削除しない |

### 仕様書を書く際の制約

**ファイル API (`specs/07-files.md`):**
- `ops.json` / `whitelist.json` は Groups 機能が管理するため、File API での書き込み・削除は禁止
- `eula.txt` は削除禁止

**監査イベント名:**
- 各仕様書の「監査イベント一覧」に記載する `action` 値は `specs/09-audit.md` のアクション一覧と一致させること
- 新しいアクション名を追加する際は両方のファイルを更新する

**パーミッション名:**
- エンドポイントの `必要権限` に使うパーミッション名は `specs/01-auth-users.md` の Permission 一覧から使うこと
- 新パーミッションを追加する場合は 01-auth-users.md の表を先に更新する

**意図的な設計の例外 (変更前に確認):**
- バックアップアップロード (`POST .../backups/upload`) は同期処理 (201)。非同期でないのは意図的
- `POST /api/v2/minecraft/versions/refresh` の権限は全認証ユーザー対象。意図的に権限を緩和している
- `schedule_expression` の記法は未定義 (TBD)。独断で定義しない

### Minecraft バージョン形式

2025 年より Mojang がバージョン形式を変更。両形式が並存する。

| 形式 | パターン | 例 |
|------|---------|-----|
| 旧形式 (〜2024) | `1.\d+(\.\d+)?` | `1.21.1`, `1.20.4` |
| 新形式 (2025〜) | `\d{2}.\d+(\.\d+)?` | `26.1`, `26.1.2` |

バリデーション正規表現 `\d+\.\d+(\.\d+)?` で両形式を網羅する。

### オープン事項 (未決定)

`docs/redesign/02-requirements.md` の Section 7 (OQ-1〜OQ-4) を参照。特に:
- **OQ-2**: ジョブキュー実装の選定 (Redis / Postgres-based / NATS 等)
- **OQ-3**: DB を SQLite のまま MVP にするか PostgreSQL にするか
