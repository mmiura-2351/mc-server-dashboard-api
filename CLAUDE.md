# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Standard Development Rules

### Rule 1: New Rule Addition Process
**Continuously improve project standards through rule documentation.**

When receiving instructions from users that appear to require ongoing compliance (not just one-time implementation):

1. Ask: "Should I make this a standard rule?"
2. If YES response is received, add it to CLAUDE.md as an additional rule
3. Apply it as a standard rule for all future interactions

This process enables continuous improvement of project rules and ensures consistent behavior across sessions.

### Rule 2: Task Completion and CI Verification
**Always verify CI passes and commit changes after completing any task.**

When completing any significant task or feature implementation:
1. **CI Verification**: Ensure all tests pass before committing
2. **Code Quality**: Run lint and format checks (`uv run ruff check app/` and `uv run ruff format app/`)
3. **Pre-commit Hooks**: Ensure pre-commit hooks are installed and pass (`uv run pre-commit install`)
4. **Commit Changes**: Create meaningful commit messages with proper documentation
5. **Status Update**: Update relevant tracking documents (e.g., CODE_REVIEW_FINDINGS.md)

### Rule 3: Test Code Development Process
**Follow systematic approach for test coverage improvement.**

When creating test coverage for services or components:
1. **Establish Target Coverage**: Set target coverage percentage based on component criticality
2. **Analyze Required Testing Elements**:
   - Analyze the service/component implementation thoroughly
   - Identify uncovered lines, error paths, and edge cases
   - Understand method signatures, exception handling, and dependencies
   - Review existing tests to avoid duplication
3. **Create Tests Based on Analysis**:
   - Create comprehensive test cases targeting specific uncovered areas
   - Focus on error handling, permission checks, and business logic validation
   - Use appropriate mocking strategies for external dependencies
4. **Iterate Until Coverage Target is Met**:
   - Run coverage reports to identify remaining gaps
   - Iterate on analysis and implementation until target coverage is achieved
   - Ensure all tests pass and maintain code quality standards

### Rule 4: Code Review Issue Creation
**Create GitHub Issues for improvements, bugs, and missing features found during code reviews.**

When reviewing source code and identifying areas for improvement:
1. **Create GitHub Issues**: For any bugs, improvement opportunities, or missing features discovered during code review
2. **Categorize Issues**: Use appropriate labels (bug, enhancement, feature-request, etc.)
3. **Provide Context**: Include relevant code references, file paths, and line numbers
4. **Document Impact**: Describe the potential impact and benefits of addressing the issue

### Rule 5: Standard Issue Resolution Process
**Follow systematic approach when fixing GitHub Issues.**

When addressing GitHub Issues, follow this standard procedure:
1. **Create Issue Branch**: Create a dedicated branch for the issue and attach it to the issue
2. **Analyze Issue Details**: Thoroughly understand the issue requirements and perform necessary analysis
3. **Create Sub-Issues**: If needed, create sub-issues to break down complex problems into manageable parts
4. **Deep Implementation Planning**: Think deeply about all elements required for implementation based on your analysis
5. **Implement Solution**: Perform the implementation and fixes following project standards
6. **Verify and Create PR**: Confirm the issue has been properly addressed and create a pull request

### Rule 6: Test Execution Guidelines
**Be mindful of test execution performance and timeouts.**

When running tests, follow these guidelines:
1. **Pre-commit Full Test Suite**: Pre-commit hooks now run the complete test suite for comprehensive quality assurance
2. **Manual Test Execution**: For manual testing, use appropriate timeout settings if needed
3. **Extend Timeout for Full Suite**: When running the complete test suite manually, explicitly extend the timeout duration (e.g., use `--timeout=300000` parameter)

### Rule 7: Issue Resolution Completion Process
**Always close resolved Issues with proper documentation and status updates.**

When completing issue resolution:
1. **Verify Resolution**: Ensure all issue requirements have been fully addressed
2. **Document Changes**: Update relevant documentation (README, CLAUDE.md, etc.) if needed
3. **Test Validation**: Confirm all tests pass and functionality works as expected
4. **Close with Summary**: Close issues with a summary of changes made and references to related PRs

### Rule 8: Git/GitHub Workflow Standards
**Follow standardized Git and GitHub practices for consistent project management.**

**Branch Management:**
1. **Issue-based Branches**: Create branches following pattern `fix/issue-{number}-{brief-description}` or `feature/issue-{number}-{brief-description}`
2. **Keep Branches Focused**: One branch per issue/feature to maintain clear history
3. **Regular Updates**: Keep feature branches updated with latest master changes

**Pull Request Workflow:**
1. **Descriptive Titles**: Use clear, descriptive PR titles that explain the change
2. **Comprehensive Descriptions**: Include summary, changes made, testing approach, and impact assessment
3. **Link Issues**: Always link related issues using "Resolves #X" or "Fixes #X"
4. **Request Reviews**: Assign appropriate reviewers and respond to feedback promptly

**Issue Management:**
1. **Clear Descriptions**: Write detailed issue descriptions with clear acceptance criteria
2. **Proper Labels**: Use appropriate labels (bug, enhancement, documentation, etc.)
3. **Priority Setting**: Assign priority levels to help with work planning
4. **Progress Updates**: Keep issues updated with progress and blockers

### Rule 9: Pull Request Review Process
**Conduct thorough code reviews and provide comprehensive feedback on GitHub Pull Requests.**

**Review Guidelines:**
1. **Comprehensive Coverage**: Review code quality, functionality, tests, documentation, and security implications
2. **Constructive Feedback**: Provide specific, actionable feedback with suggestions for improvement
3. **Code Standards**: Verify adherence to project coding standards and architectural patterns
4. **Testing Verification**: Ensure adequate test coverage and that all tests pass

**Review Process:**
1. **Use GitHub CLI**: Utilize `gh pr view` and `gh pr review` commands for efficient review workflow
2. **Structured Comments**: Organize feedback into categories (bugs, improvements, questions, suggestions)
3. **Approval Criteria**: Only approve PRs that meet all quality standards and fully address the issue
4. **Follow-up Actions**: Track that feedback is addressed before final approval and merge

### Rule 10: Pull Request Merge Strategy
**Use squash merge as the default merge strategy for pull requests.**

When merging pull requests:
1. **Default to Squash Merge**: Use `gh pr merge <number> --squash` to maintain a clean commit history
2. **Clean Commit Message**: Ensure the squashed commit has a clear, descriptive message
3. **Delete Merged Branches**: Always delete the feature branch after successful merge
4. **Update Related Issues**: Ensure linked issues are properly closed with the merge

Benefits of squash merge:
- Maintains clean, linear commit history
- Groups all PR changes into a single commit
- Makes it easier to revert changes if needed
- Keeps the main branch history readable

## Project Overview

This repository contains two parallel contexts:

- **`master` ブランチ (v1)**: FastAPI で実装済みの稼働中 API。ユーザー認証・RBAC・リアルタイム監視・バックアップ・サーバーライフサイクル管理を提供する
- **`redesign/v2-requirements` ブランチ (v2)**: 実装を含まない要件定義・仕様書専用ブランチ。`docs/redesign/` 配下にドキュメントのみを置く

---

## V2 再設計ドキュメント (`redesign/v2-requirements` ブランチ)

**このブランチは実装を含まない。** `docs/redesign/` の Markdown ファイルを編集することだけが作業対象。

### ドキュメント構成

```
docs/redesign/
├── README.md                   # 全体概要・決定済み事項
├── 01-current-issues.md        # v1 の設計破綻の分析
├── 02-requirements.md          # v2 機能/非機能要件 (FR-O-*, FR-S-*, NFR-*)
├── 03-architecture-direction.md # アーキテクチャ方針 (叩き台)
├── 04-feature-list.md          # v1 機能一覧と v2 での扱い
└── specs/
    ├── 01-auth-users.md        # 認証 / Organization / ユーザー管理
    ├── 02-groups.md            # プレイヤーグループ (Minecraft OP/whitelist)
    ├── 03-servers.md           # サーバー管理・制御
    ├── 04-versions.md          # Minecraft バージョン管理
    ├── 05-backups.md           # バックアップ管理 / スケジューラー
    ├── 06-jobs.md              # ジョブ管理 (非同期タスク共通仕様)
    ├── 07-files.md             # ファイル管理 / 編集履歴
    ├── 08-realtime.md          # リアルタイム通信 (WebSocket)
    └── 09-audit.md             # 監査ログ
```

### 決定済み設計方針 (再議論しない)

以下は議論を経て確定した決定事項。新しい仕様を書く際にこれらに反しないこと。

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
- **OQ-3**: DB を SQLite のまま MVP にするか PostgreSQL にするか (`03-architecture-direction.md` は PostgreSQL を推奨)

---

## Development Commands

| Task              | Command                       |
|-------------------|-------------------------------|
| Start application | `uv run fastapi dev`          |
| Lint code         | `uv run ruff check app/`      |
| Format code       | `uv run ruff format app/`     |
| Type checking     | `uv run mypy app/` (currently disabled in pre-commit) |
| Run tests         | `uv run pytest`               |
| Run single test   | `uv run pytest tests/test_filename.py::test_function_name` |
| Check code coverage | `uv run coverage run -m pytest && uv run coverage report` |
| Install pre-commit hooks | `uv run pre-commit install` |
| Run pre-commit on all files | `uv run pre-commit run --all-files` |
| Run specific pre-commit hook | `uv run pre-commit run <hook-name>` |

## System Architecture

### Core Service Integration
The application follows a layered architecture with tight integration between components:

- **Startup Lifecycle**: `app/main.py` coordinates initialization of database, backup scheduler, WebSocket monitoring, and server synchronization
- **Service Layer**: `app/services/` contains business logic that orchestrates between different domains
- **Database Integration**: Automatic server state synchronization between filesystem and database on startup
- **Real-time Features**: WebSocket service provides live server monitoring and log streaming
- **Background Processing**: Backup scheduler runs automated backup operations

### Key Architectural Patterns

**Multi-Domain Resource Management**: The system manages interconnected resources (servers, groups, backups, templates) with complex relationships. Always consider cross-domain impacts when making changes.

**Service Orchestration**:
- `minecraft_server_manager`: Physical server process management
- `database_integration_service`: Sync between filesystem and database state
- `backup_scheduler`: Automated backup operations
- `websocket_service`: Real-time communication and monitoring

**Role-Based Security Model**:
- Users have `is_active` (can authenticate) and `is_approved` (admin-approved) flags
- Three roles: admin, operator, user with hierarchical permissions
- First registered user automatically becomes admin with approval

### Domain Structure

**Server Management** (`app/servers/`):
- Manages physical Minecraft server processes and configurations
- Handles JAR downloads, version management, and server lifecycle
- Integrates with file system for server directories in `./servers/`

**Group Management** (`app/groups/`):
- Dynamic OP/whitelist groups that can attach to multiple servers
- Player management with UUID tracking and Minecraft API integration
- Server attachments with priority levels

**Backup System** (`app/backups/`):
- Automated and manual backup creation with metadata tracking
- Server restoration with new server creation from backups
- Scheduler integration for background operations

**Template System** (`app/templates/`): *(v1 のみ。v2 設計では廃止)*
- Reusable server configurations created from existing servers
- Template cloning and customization capabilities
- Integration with server creation workflow

**File Management** (`app/files/`):
- Secure file operations within server directories
- Path validation to prevent directory traversal attacks
- Real-time file reflection for configuration changes

## Environment Setup

### Initial Project Setup

1. **Install dependencies:**
   ```bash
   uv sync --group dev
   ```

2. **Install pre-commit hooks:**
   ```bash
   uv run pre-commit install
   ```

3. **Create `.env` file:**
   ```bash
   cp .env.example .env  # Edit with your values
   ```

### Required Environment Variables

Required `.env` variables:
```
SECRET_KEY=your-secret-key
DATABASE_URL=sqlite:///./app.db
```

Optional configuration:
```
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
```

### Pre-commit Hooks

The project uses pre-commit hooks to ensure code quality:
- **Ruff**: Linting and formatting
- **MyPy**: Type checking  
- **Standard checks**: Trailing whitespace, file endings, YAML/JSON validation
- **Security**: Basic secret detection

Hooks run automatically on commit. To run manually:
```bash
uv run pre-commit run --all-files
```

## Database Dependency Injection

Use `Depends(get_db)` pattern for database sessions:
```python
from app.core.database import get_db
from sqlalchemy.orm import Session

async def endpoint(db: Session = Depends(get_db)):
    # Database operations here
```

## Testing Strategy

### Unit Tests (`uv run pytest`)
- Comprehensive fixtures in `conftest.py` with different user roles
- Database overrides pattern: `app.dependency_overrides[get_db]`
- Isolated test database for each test session

**Test Coverage**: Comprehensive unit tests covering all API endpoints across 7 feature areas.

**Screenshot Evidence Collection** (for development debugging):
- Screenshots can be saved to `./screenshots/{timestamp}/` with numbered filenames when debugging
- File naming format: `{number}_{api_name}_{action}.png` (e.g., `01_user_registration.png`, `05_server_create.png`)
- Screenshot directory is gitignored for development purposes

## Development Flow

### Feature Implementation Process
1. **Domain Analysis**: Map requirements to use cases (UC1-46) and identify affected services
2. **Service Integration**: Consider impact on minecraft_server_manager, backup_scheduler, and websocket_service
3. **Security Review**: Validate role-based access and resource ownership
4. **Cross-Domain Testing**: Test interactions between servers, groups, backups, and templates
5. **Real-time Verification**: Ensure WebSocket events are properly emitted for UI updates

### Database Schema Evolution
- Models auto-create tables via SQLAlchemy on startup
- Database relationships span multiple domains (users → servers → groups → backups)
- Consider migration strategy for schema changes affecting existing data

### Code Quality Standards
- Ruff formatting and linting with 90-character line length
- Import sorting enabled via Ruff
- Type hints required for all new code
- MyPy type checking for static analysis
- Pre-commit hooks for automated quality checks
- Comprehensive test coverage for business logic

## Security Considerations

- **Authentication**: JWT tokens with configurable expiration
- **Authorization**: Three-tier role system with resource ownership validation
- **File Security**: Path traversal protection in file operations
- **Input Validation**: Pydantic models validate all request/response data
- **Process Isolation**: Server processes run in controlled environment

## Key Integration Points

When modifying the system, pay attention to these critical integration points:

1. **Server Lifecycle**: Changes to server management must sync with database_integration_service
2. **Group Attachments**: Server and group modifications trigger config file updates
3. **Backup Operations**: Server state changes affect backup validity and restoration
4. **WebSocket Events**: Real-time updates require proper event emission
5. **Template Dependencies** *(v1 のみ)*: Server and template modifications must maintain consistency

This architecture enables complex multi-server management while maintaining data consistency and real-time responsiveness across all system components.
