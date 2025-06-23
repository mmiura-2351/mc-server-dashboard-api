# Development Guide

Complete guide for developing, testing, and deploying the Minecraft Server Dashboard API.

## Environment Setup

### Prerequisites
- uv package manager (automatically manages Python 3.13+ requirement)
- Java Runtime Environment (for Minecraft servers)
- Git for version control

### Installation

1. **Clone and Setup**:
   ```bash
   git clone <repository-url>
   cd mc-server-dashboard-api
   uv sync
   ```

2. **Environment Configuration**:
   Create `.env` file:
   ```env
   SECRET_KEY=your-secret-key-here
   DATABASE_URL=sqlite:///./app.db
   CORS_ORIGINS=["http://localhost:3000"]
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=30
   ```

3. **Database Initialization**:
   ```bash
   uv run fastapi dev  # Creates tables automatically
   ```

### Development Commands

| Command | Description |
|---------|-------------|
| `uv run fastapi dev` | Start development server |
| `uv run pytest` | Run tests |
| `uv run pytest --timeout=300000` | Run full test suite with extended timeout |
| `uv run ruff check app/` | Code quality checks |
| `uv run black app/` | Format code |
| `uv run coverage run -m pytest && uv run coverage report` | Generate coverage report |
| `uv run coverage html` | Generate HTML coverage report |

## Project Structure

```
mc-server-dashboard-api/
├── app/                        # Main application package
│   ├── main.py                # Application entry point & lifespan management
│   ├── core/                  # Core configuration and database
│   │   ├── config.py         # Settings and configuration
│   │   ├── database.py       # Database connection and session management
│   │   └── exceptions.py     # Custom exception classes
│   ├── middleware/            # Request/response middleware
│   │   ├── audit_middleware.py
│   │   └── performance_monitoring.py
│   ├── services/              # Business logic services
│   │   ├── minecraft_server.py      # Process management
│   │   ├── database_integration.py  # State synchronization  
│   │   ├── backup_scheduler.py      # Automated backups
│   │   ├── websocket_service.py     # Real-time features
│   │   └── [other services...]
│   ├── [domain]/              # Feature domains
│   │   ├── models.py         # Database models
│   │   ├── schemas.py        # Pydantic validation models
│   │   ├── router.py         # HTTP endpoints
│   │   └── service.py        # Domain-specific business logic
│   └── types.py              # Shared type definitions
├── tests/                     # Test suite
├── docs/                      # Documentation
├── servers/                   # Server file storage
├── backups/                   # Backup file storage
├── file_history/             # File version storage
└── pyproject.toml            # Project configuration
```

## Testing Strategy

### Unit Testing with pytest

#### Running Tests

```bash
# Run all tests
uv run pytest

# Run with extended timeout for full suite
uv run pytest --timeout=300000

# Run specific test file
uv run pytest tests/test_filename.py

# Run specific test function
uv run pytest tests/test_filename.py::test_function_name

# Run with verbose output
uv run pytest -v

# Run tests and show print statements
uv run pytest -s

# Run tests with coverage
uv run coverage run -m pytest && uv run coverage report

# Generate HTML coverage report
uv run coverage html
```

#### Test Organization

**Test Structure**:
- All tests in `/tests/` directory
- Comprehensive fixtures in `conftest.py`
- Database overrides: `app.dependency_overrides[get_db]`
- Isolated test database for each session

**Test Categories**:
1. **Router Tests** - API endpoint testing with authentication/authorization
2. **Service Tests** - Business logic with mocking
3. **Integration Tests** - Database integration and service interaction
4. **Security Tests** - Authentication, authorization, input validation
5. **Performance Tests** - Middleware and monitoring functionality

#### Test Fixtures

**User Fixtures**:
- `test_user` - Standard user for basic testing
- `operator_user` - Operator role for server management testing
- `admin_user` - Admin role for system-wide testing
- `unapproved_user` - User without approval for approval flow testing

**Database Fixtures**:
- `test_db` - Isolated test database session
- `client` - FastAPI test client with dependency overrides

**Server Fixtures**:
- `test_server` - Basic Minecraft server for testing
- `running_server` - Server in running state for status testing

#### Mock Strategy

- **External APIs**: Mock Minecraft API and Mojang API calls
- **File System**: Mock file operations when testing business logic
- **Database**: Use real database operations in integration tests
- **Subprocess**: Mock server process calls for unit testing

### Test Coverage Standards

- **Target**: >90% coverage on critical business logic
- **Focus Areas**: Error paths, edge cases, role-based access control
- **Security Testing**: Input validation, authentication, authorization
- **Performance Testing**: Request times, database queries, WebSocket connections

### Configuration

**pytest.ini**:
```ini
[tool:pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

**Coverage Configuration** (pyproject.toml):
```toml
[tool.coverage.run]
source = ["app"]
omit = ["*/tests/*", "*/__init__.py", "*/venv/*", "*/.venv/*"]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if self.debug:",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:"
]
show_missing = true
precision = 2
```

## Code Quality Standards

### Formatting and Linting

**Black Configuration** (pyproject.toml):
```toml
[tool.black]
line-length = 90
target-version = ["py313"]
skip-string-normalization = false
```

**Ruff Configuration** (pyproject.toml):
```toml
[tool.ruff]
line-length = 90
target-version = "py313"
exclude = ["tests/", ".venv"]
fix = true

[tool.ruff.lint]
extend-select = ["I"]  # Enable import sorting
```

### Code Standards

1. **Type Hints**: Required for all new code
2. **Docstrings**: Required for public methods and classes
3. **Error Handling**: Comprehensive exception handling
4. **Security**: Input validation, path traversal protection
5. **Performance**: Async/await patterns, efficient database queries

### Pre-commit Workflow

```bash
# Format code
uv run black app/

# Check code quality
uv run ruff check app/

# Fix auto-fixable issues
uv run ruff check app/ --fix

# Run tests
uv run pytest
```

## Development Workflow

### Feature Development Process

1. **Create Feature Branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Development**:
   - Follow domain-driven design patterns
   - Write tests first (TDD encouraged)
   - Implement business logic in services
   - Add HTTP endpoints in routers
   - Update documentation as needed

3. **Quality Checks**:
   ```bash
   uv run black app/
   uv run ruff check app/
   uv run pytest
   ```

4. **Commit and Push**:
   ```bash
   git add .
   git commit -m "feat: add new feature"
   git push origin feature/your-feature-name
   ```

### API Development Guidelines

#### Router Organization
- Group related endpoints in domain-specific routers
- Use appropriate HTTP methods (GET, POST, PUT, DELETE, PATCH)
- Implement proper status codes and error responses
- Add comprehensive OpenAPI documentation

#### Schema Design
- Use Pydantic models for request/response validation
- Separate models for different operations (Create, Update, Response)
- Include proper field validation and constraints
- Document all schema fields

#### Service Layer Patterns
- Keep business logic in service classes
- Use dependency injection for database sessions
- Implement proper error handling and logging
- Follow async/await patterns for I/O operations

### Database Development

#### Model Guidelines
- Use SQLAlchemy ORM models
- Include proper relationships and constraints
- Add appropriate indexes for performance
- Use enums for fixed value sets

#### Migration Strategy
- SQLAlchemy auto-creates tables on startup
- Use proper foreign key constraints
- Consider data migration scripts for major changes
- Test migrations with sample data

## Authentication & Security

### Development Security Practices

1. **Environment Variables**: Never commit secrets to version control
2. **Input Validation**: Use Pydantic models for all inputs
3. **SQL Injection**: Use SQLAlchemy ORM, avoid raw queries
4. **Path Traversal**: Validate file paths in file operations
5. **CORS**: Configure appropriate origins for frontend integration

### Testing Security Features

```python
# Example security test
def test_unauthorized_access(client):
    """Test that protected endpoints require authentication"""
    response = client.get("/api/v1/servers/")
    assert response.status_code == 401

def test_role_based_access(client, test_user, admin_user):
    """Test role-based access control"""
    # User cannot access admin endpoints
    user_response = client.get("/api/v1/users/", headers=auth_headers(test_user))
    assert user_response.status_code == 403

    # Admin can access admin endpoints
    admin_response = client.get("/api/v1/users/", headers=auth_headers(admin_user))
    assert admin_response.status_code == 200
```

## Performance Considerations

### Database Optimization
- Use appropriate indexes on frequently queried columns
- Implement pagination for large datasets
- Use connection pooling for database connections
- Optimize N+1 query problems with proper eager loading

### Async Programming
- Use async/await for I/O operations
- Leverage aiofiles for file operations
- Implement async database operations
- Use async context managers for resource management

### Monitoring and Metrics
- Performance monitoring middleware tracks request times
- Database query performance monitoring
- Memory usage tracking for server processes
- WebSocket connection monitoring

## Debugging and Troubleshooting

### Common Development Issues

**Database Connection Issues**:
```bash
# Check database file permissions
ls -la app.db

# Verify SQLAlchemy connection
uv run python -c "from app.core.database import engine; print(engine.execute('SELECT 1').scalar())"
```

**Service Startup Issues**:
```bash
# Check logs for service initialization
uv run fastapi dev --log-level debug

# Verify file system permissions
ls -la servers/ backups/ file_history/
```

**Test Failures**:
```bash
# Run specific failing test with verbose output
uv run pytest tests/test_filename.py::test_function -v -s

# Check test database state
uv run python -c "from tests.conftest import test_db; print(test_db)"
```

### Development Tools

**API Testing**:
- Interactive docs: `http://localhost:8000/docs`
- ReDoc documentation: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/health`

**Database Inspection**:
```bash
# SQLite browser for database inspection
sqlite3 app.db ".schema"
sqlite3 app.db "SELECT * FROM users;"
```

**Log Analysis**:
- Application logs show service initialization and errors
- Audit logs track all user actions
- Performance logs identify slow requests

## Deployment

### Production Considerations

1. **Environment Variables**:
   ```env
   SECRET_KEY=production-secret-key
   DATABASE_URL=postgresql://user:pass@localhost/dbname
   CORS_ORIGINS=["https://yourdomain.com"]
   ```

2. **Database**:
   - Use PostgreSQL or MySQL for production
   - Configure proper connection pooling
   - Set up regular database backups
   - Monitor database performance

3. **Security**:
   - Use HTTPS in production
   - Configure proper CORS origins
   - Set secure JWT expiration times
   - Enable audit logging

4. **Performance**:
   - Use production ASGI server (uvicorn with workers)
   - Configure reverse proxy (nginx)
   - Set up monitoring and alerting
   - Optimize database queries

### Docker Deployment

**Dockerfile Example**:
```dockerfile
FROM python:3.13-slim

WORKDIR /app
COPY . .

RUN pip install uv
RUN uv sync --frozen

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Health Monitoring

**Health Check Endpoint**:
- `/health` - Service status and health information
- `/metrics` - Performance metrics and statistics

**Monitoring Points**:
- Database connectivity
- Service initialization status
- External API availability
- Process health and resource usage

## Contributing Guidelines

### Code Review Process

1. **Pull Request Requirements**:
   - All tests must pass
   - Code coverage maintained
   - Code style checks pass
   - Documentation updated

2. **Review Criteria**:
   - Code quality and readability
   - Security considerations
   - Performance implications
   - Test coverage adequacy

### Best Practices

1. **Commit Messages**: Use conventional commits format
2. **Branch Naming**: Use descriptive branch names (feature/, fix/, docs/)
3. **Documentation**: Update relevant documentation with changes
4. **Testing**: Write tests for new functionality
5. **Security**: Consider security implications of all changes

This development guide provides the foundation for contributing to and maintaining the Minecraft Server Dashboard API with high quality, security, and performance standards.
