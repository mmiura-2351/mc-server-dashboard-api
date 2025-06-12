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
2. **Code Quality**: Run lint and format checks (`uv run ruff check app/` and `uv run black app/`)
3. **Commit Changes**: Create meaningful commit messages with proper documentation
4. **Status Update**: Update relevant tracking documents (e.g., CODE_REVIEW_FINDINGS.md)

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
1. **Avoid Full Test Suite Timeouts**: Running all tests may result in timeouts. Focus on running minimal, targeted tests when possible
2. **Extend Timeout for Full Suite**: When running the complete test suite is necessary, explicitly extend the timeout duration (e.g., use `--timeout=300000` parameter)

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

## Project Overview

This is a comprehensive FastAPI-based backend API for managing multiple Minecraft servers. The system provides user authentication, role-based access control, real-time monitoring, backup management, and complete server lifecycle management covering 46 specific use cases.

## Development Commands

| Task              | Command                       |
|-------------------|-------------------------------|
| Start application | `uv run fastapi dev`          |
| Lint code         | `uv run ruff check app/`      |
| Format code       | `uv run black app/`           |
| Run tests         | `uv run pytest`               |
| Run single test   | `uv run pytest tests/test_filename.py::test_function_name` |
| Check code coverage | `uv run coverage run -m pytest && uv run coverage report` |
| Start browser test environment | `./testing/scripts/test_server.sh start` |
| Stop browser test environment | `./testing/scripts/test_server.sh stop` |

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

**Template System** (`app/templates/`):
- Reusable server configurations created from existing servers
- Template cloning and customization capabilities
- Integration with server creation workflow

**File Management** (`app/files/`):
- Secure file operations within server directories
- Path validation to prevent directory traversal attacks
- Real-time file reflection for configuration changes

## Environment Setup

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

### Browser-based API Testing
Complete visual verification system using Playwright:

```bash
# Start isolated test environment
./testing/scripts/test_server.sh start

# Test environment features:
# - API server on port 8001 with test database (test_app.db)
# - Web interface on port 8002 for manual testing
# - First user auto-becomes admin
# - Automatic cleanup on stop
```

**Test Coverage**: All 30+ API endpoints across 7 feature areas with automated screenshot capture for visual evidence.

**Screenshot Evidence Collection**:
- Screenshots saved to `./screenshots/{timestamp}/` with numbered filenames  
- File naming format: `{number}_{api_name}_{action}.png` (e.g., `01_user_registration.png`, `05_server_create.png`)
- Full-page screenshots capture both request forms and response panels
- Test areas include: Authentication, Server Management, Group Management, Backup Management, Template Management, File Management, and System Administration
- Each test session creates a timestamped directory with README.md documenting the test sequence
- Use `savePng: true` and specify custom `downloadsDir: "./screenshots/{timestamp}/"` for Playwright screenshot calls
- Screenshot directory is gitignored for development testing purposes

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
- Black formatting with 90-character line length
- Ruff linting with import sorting enabled
- Type hints required for all new code
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
5. **Template Dependencies**: Server and template modifications must maintain consistency

This architecture enables complex multi-server management while maintaining data consistency and real-time responsiveness across all system components.
