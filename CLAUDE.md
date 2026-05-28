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
**Be mindful of test execution performance and timeouts. Tests are split into a layered execution strategy — see [`docs/TESTING.md`](docs/TESTING.md) for the canonical policy.**

| Stage | Scope | Command | Typical time |
|---|---|---|---|
| pre-commit | unit smoke (`-m "not slow"`) | `pytest tests/unit -m "not slow"` | ~60–70 s |
| pre-push | unit + integration smoke (`-m "not slow"`) | `pytest tests/unit tests/integration -m "not slow"` | ~2 min |
| CI on push (`ci.yaml`) | full suite incl. `slow` | `just test` | < 5 min |
| CI nightly (`nightly.yaml`) | full suite + coverage | `just coverage` | < 10 min |

Operational notes:
1. **Install both hook stages once**: `uv run pre-commit install --hook-type pre-commit --hook-type pre-push`. The pre-push stage will not run automatically without `--hook-type pre-push`.
2. **Manual full-suite run**: prefer `just test` over invoking `pytest` directly; it inherits the project's standard options.
3. **Extend timeout for full suite**: when running the complete suite manually under tooling that imposes a timeout, explicitly extend it (e.g. `--timeout=300000`).
4. **Mark new slow tests**: any test that takes ≥ 1 s or spawns a subprocess must carry `@pytest.mark.slow` (or `pytestmark = pytest.mark.slow` at file level). See `docs/TESTING.md` §3.
5. **Pre-push fails without a JRE on `PATH`**: the integration smoke set includes server-creation API tests that invoke Java discovery. Until [#209](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/209) annotates them with `@pytest.mark.requires_java`, push from a machine with Java installed, or bypass with `git push --no-verify` if you understand the risk.

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

### Rule 11: Documentation Language Policy
**All documentation in this project must be written in English.**

This applies to every Markdown file under the repo (README.md, CLAUDE.md, CHANGELOG.md, `docs/**/*.md`, `deployment/**/*.md`, `.github/**/*.md`, etc.) and to PR descriptions, issue templates, and inline doc comments.

1. **New content**: Always write new documentation in English.
2. **Touching existing docs**: When editing a doc that still contains Japanese sections, translate those sections to English as part of the change rather than mixing languages.
3. **CHANGELOG entries**: Concise English bullets that still cover everything notable in the release — do not summarize substantive changes away, but keep each entry short.
4. **Code identifiers and commit messages**: Out of scope for this rule (covered by existing project conventions).

## Project Overview

This is a comprehensive FastAPI-based backend API for managing multiple Minecraft servers. The system provides user authentication, role-based access control, real-time monitoring, backup management, and complete server lifecycle management covering 46 specific use cases.

## Development Commands

Tasks are run with [`just`](https://github.com/casey/just). Run `just` (no args) to list all recipes.

| Task              | Command                       |
|-------------------|-------------------------------|
| Start application | `just dev` (or `uv run fastapi dev`) |
| Lint code         | `just lint`                   |
| Format code       | `just format`                 |
| Type checking     | `uv run mypy app/` (enabled in pre-commit with a relaxed config per Issue #86) |
| Run tests         | `just test`                   |
| Run single test   | `uv run pytest tests/test_filename.py::test_function_name` |
| Check code coverage | `just coverage`             |
| Install pre-commit hooks | `uv run pre-commit install` |
| Run pre-commit on all files | `uv run pre-commit run --all-files` |
| Run specific pre-commit hook | `uv run pre-commit run <hook-name>` |

If `just` is not installed, see the project README for installation instructions (`cargo install just`, `brew install just`, or `apt install just`).

## System Architecture

> **The canonical architecture document is [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**: the target hexagonal (Ports & Adapters) layering, the four-layer per-domain structure (`domain/` / `application/` / `adapters/` / `api/`), and the rules new code must follow. See §17.4 for the current per-domain migration snapshot. The notes below summarize the runtime wiring that supplements the architecture doc.

### Core Service Integration

- **Startup Lifecycle**: `app/main.py` coordinates initialization of the database, backup scheduler, WebSocket monitoring, and server synchronization.
- **Hexagonal Domains**: Business logic lives in per-domain `application/` use cases that depend on Ports defined in `domain/ports.py`. Concrete adapters in `adapters/` are wired through `api/dependencies.py`. Earlier monolithic services under `app/services/` have been decomposed into domain layers (Issue #154).
- **Cross-cutting Ports**: `app/core/ports.py` exposes shared Ports (`Clock`, `PermissionChecker`, etc.); `app/audit/domain/ports.py` exposes `AuditWriter`, injected via per-domain `api/dependencies.py` (AuditWriter DI migration, PR #401).
- **Database Integration**: Filesystem ↔ database server state sync runs on startup (`AUTO_SYNC_ON_STARTUP`).
- **Real-time**: WebSocket service streams live server status and logs; real-time RCON commands are dispatched through `RealTimeServerCommandService` (helper) → `MinecraftServerManager.send_command()` (primary).
- **Background**: Backup scheduler runs automated backups and periodic cleanup of `.pending/` / `.failed/` directories.

### Key Architectural Patterns

**Multi-Domain Resource Management**: Servers, groups, and backups have non-trivial cross-domain relationships. When changing one, check impacts on the others (especially Group attachments → server config file regeneration and Backup ↔ Server restore flow).

**Role-Based Security Model**:
- Users have `is_active` (can authenticate) and `is_approved` (admin-approved) flags.
- Three roles: admin, operator, user with hierarchical permissions.
- First registered user automatically becomes admin with approval.

### Domain Structure

Every domain has the full hexagonal layering today; the only differences are at the HTTP boundary (some still use a flat `router.py`, see ARCHITECTURE.md §17.4).

- **`app/servers/`** — Minecraft server lifecycle. The process manager was split into mixins (`DaemonProcessMixin`, `PidFileMixin`, `PreflightMixin`, `MonitoringMixin`, PR #389). HTTP routes are split across `app/servers/routers/{control,management,utilities,import_export}.py`.
- **`app/groups/`** — Dynamic OP/whitelist groups, with UUID tracking and real-time application via RCON.
- **`app/backups/`** — Backup creation/restore/scheduling.
- **`app/files/`** — Secure server-file operations; the former `file_management_service` was split into focused modules under `app/files/application/management/` (PR #388).
- **`app/audit/`** — Cross-cutting audit logging via the `AuditWriter` Port (PR #401).
- **`app/auth/`, `app/users/`, `app/versions/`, `app/health/`, `app/websockets/`** — Self-explanatory; all on the standard layout.

## Environment Setup

### Initial Project Setup

1. **Install dependencies:**
   ```bash
   uv sync --group dev
   ```

2. **Install pre-commit hooks (both stages):**
   ```bash
   uv run pre-commit install --hook-type pre-commit --hook-type pre-push
   ```

3. **Create `.env` file:**
   ```bash
   cp .env.example .env  # Edit with your values
   ```

#### Optional: Nix devShell

A minimal [`flake.nix`](flake.nix) provides a reproducible system toolchain (Python 3.13, `uv`, JDK 21, `just`, `pre-commit`, `git`). It is strictly opt-in — the `uv sync` workflow above continues to work without Nix. With direnv + nix-direnv:

```bash
direnv allow   # auto-loads the devShell from .envrc → `use flake`
```

See README.md for the full Nix walkthrough.

### Required Environment Variables

Required `.env` variables:
```
SECRET_KEY=your-secret-key   # ≥ 32 chars, no weak prefixes
DATABASE_URL=sqlite:///./app.db
```

All other settings (auth, DB pool, file uploads, concurrency limits, password policy, brute-force protection, daemon settings, etc.) are documented in [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) along with per-environment defaults.

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

> **Where does a new test go?** See [`docs/TESTING.md`](docs/TESTING.md) for the canonical test hierarchy policy (unit / integration / infrastructure), classification rules, and pytest marker usage. The notes below cover only project-specific fixtures and conventions.

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
4. **Cross-Domain Testing**: Test interactions between servers, groups, and backups
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

This architecture enables complex multi-server management while maintaining data consistency and real-time responsiveness across all system components.
