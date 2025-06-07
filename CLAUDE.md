# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI-based backend API for managing Minecraft servers. The application provides user authentication, role-based access control, and user management functionality.

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

## System Requirements Overview

This system is a Minecraft server management dashboard providing 46 use cases across these key areas:

### Core Feature Areas
1. **Server Management** (UC1-7): Multi-server creation, configuration, templates, version/type selection
2. **Server Operations** (UC8-11): Start/stop/delete servers, configuration updates
3. **Player Management** (UC12-19): OP/whitelist group management with dynamic server attachment
4. **Monitoring** (UC20): Real-time server status monitoring
5. **Backup Management** (UC21-28): Automated backups, restoration, server creation from backups
6. **File Management** (UC29-37): File operations, import/export, template management
7. **Account Management** (UC38-42): User authentication and account operations
8. **Admin Functions** (UC43-46): User approval, role management

### Key Design Considerations
- **Multi-server Architecture**: Unique server IDs with database management
- **Group Management**: Dynamic OP/whitelist groups with multi-server attachment
- **Real-time Updates**: WebSocket-based status monitoring and instant file reflection
- **Security**: File operation restrictions, role-based access control
- **Backup System**: Automated scheduling with metadata management

## Development Flow

### Basic Development Process
1. **Requirements Understanding**: Accurately understand user needs and map to relevant use cases (UC1-46)
2. **Design Planning**: Identify required components (models, endpoints, business logic, etc.)
3. **Design Documentation**: Document the implementation plan
4. **Implementation**: Code based on the design
5. **Quality Assurance**: Run tests and formatting, monitor test coverage
   ```bash
   uv run ruff check app/
   uv run black app/
   uv run pytest
   ```

### Environment Setup
- Create `.env` file with required variables:
  ```
  SECRET_KEY=your-secret-key
  DATABASE_URL=sqlite:///./app.db
  ```

## Architecture

### Core Structure
- **app/main.py**: FastAPI application entry point with CORS middleware and router registration
- **app/core/**: Core configuration and database setup
  - `config.py`: Pydantic settings management with .env file support
  - `database.py`: SQLAlchemy engine, session management, and dependency injection
- **app/auth/**: Authentication system with JWT tokens
  - `dependencies.py`: OAuth2 security scheme and user authentication dependency
  - `auth.py`: Token creation and verification logic
- **app/users/**: User management with role-based access control
  - `models.py`: User SQLAlchemy model with Role enum (admin, operator, user)
- **app/services/**: Business logic layer

### Key Architecture Patterns

**Database Dependency Injection**: Use `Depends(get_db)` to inject database sessions into route handlers. The `get_db()` function provides proper session lifecycle management.

**Authentication Flow**:
1. Users authenticate via `/auth/token` endpoint
2. JWT tokens are validated using `get_current_user` dependency
3. Role-based access control through User.role enum
4. User approval system (is_approved field)

**User States**: Users have two boolean flags:
- `is_active`: Controls if user can authenticate
- `is_approved`: Controls if user has been approved by admin

### Testing Strategy
- **Test Database**: Uses separate SQLite database (`test.db`) for testing
- **Fixtures**: Comprehensive fixtures in `conftest.py` including test users with different roles
- **Database Overrides**: `app.dependency_overrides[get_db]` pattern for test isolation
- **User Fixtures**: Pre-built fixtures for `test_user`, `admin_user`, and `unapproved_user`

#### Browser-based API Testing with Playwright

The project includes a comprehensive browser-based testing system that provides visual verification of all API endpoints. This system uses Playwright for browser automation and a dedicated test server environment.

**Test Environment Setup:**
```bash
# Start test environment (API server on port 8001, web interface on port 8002)
./testing/scripts/test_server.sh start

# Stop test environment and clean up
./testing/scripts/test_server.sh stop

# Check status of both servers
./testing/scripts/test_server.sh status
```

**Test Server Script (`./testing/scripts/test_server.sh`):**
- **Isolated Environment**: Uses separate test database (`test_app.db`) that is cleaned on start/stop
- **Dual Server Setup**: Runs API server on port 8001 and web interface on port 8002
- **First User Auto-Admin**: The first registered user automatically gets admin privileges and approval
- **Automatic Cleanup**: Database, logs, and PID files are cleaned up when stopped

**Web Testing Interface (`./testing/web/index.html`):**
- **Comprehensive API Coverage**: Tests all 30+ API endpoints across all feature areas
- **Visual Response Display**: Shows request/response data in real-time with syntax highlighting
- **Pre-configured Test Data**: Includes sample data for servers, groups, backups, and templates
- **Authentication Flow**: Full user registration, login, and token management
- **Complex Scenarios**: Multi-step workflows like server creation → group creation → attachment

**Playwright Integration:**
```bash
# Example: Automated browser testing with screenshot capture
# Screenshots are saved to ~/Screenshots/{timestamp}/ with numbered filenames
```

**Test Coverage Areas:**
1. **Authentication**: User registration, login, token validation
2. **Server Management**: Create, list, details, status, supported versions
3. **Group Management**: Create, list, details, player management, server attachment
4. **Backup Management**: Create, list, details, restore, statistics, scheduler status
5. **Template Management**: Create from server, custom creation, details, cloning
6. **File Management**: List files, read/write operations, file search
7. **Complex Scenarios**: Multi-API workflows and integration testing

**Key Testing Features:**
- **Visual Evidence**: Full-page screenshots for each API test execution
- **Error Validation**: Tests both success and failure scenarios
- **Data Persistence**: Verifies data consistency across related API calls
- **Role-based Testing**: Tests different user permission levels
- **Real-time Feedback**: Immediate visual confirmation of API responses


### Configuration
- **Environment Variables**: Uses .env file with required variables:
  - `SECRET_KEY`: JWT signing key
  - `DATABASE_URL`: SQLite database path
  - Optional: `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`
- **Code Style**: Black formatting with 90-character line length, Ruff linting with import sorting

### Development Notes
- SQLAlchemy models use declarative_base from `app.core.database.Base`
- Database tables are auto-created on application startup via lifespan events
- CORS is configured to allow localhost:3000 for frontend development
- Uses bcrypt for password hashing via passlib
