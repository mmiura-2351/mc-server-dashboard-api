# Testing Strategy

The Minecraft Server Dashboard API uses a comprehensive testing approach based on pytest with asyncio support and comprehensive fixtures.

## Unit Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with extended timeout for full suite
uv run pytest --timeout=300000

# Run specific test file
uv run pytest tests/test_filename.py

# Run specific test function
uv run pytest tests/test_filename.py::test_function_name

# Run with coverage
uv run coverage run -m pytest && uv run coverage report

# Generate HTML coverage report
uv run coverage html
```

### Test Structure

**Test Organization:**
- All tests located in `/tests/` directory
- Comprehensive fixtures in `conftest.py` with different user roles
- Database overrides pattern: `app.dependency_overrides[get_db]`
- Isolated test database for each test session

**Key Test Categories:**
1. **Router Tests** - API endpoint testing with authentication and authorization
2. **Service Tests** - Business logic testing with mocking
3. **Integration Tests** - Database integration and service interaction
4. **Security Tests** - Authentication, authorization, and input validation
5. **Performance Tests** - Middleware and monitoring functionality

### Test Fixtures

**User Fixtures:**
- `test_user` - Standard user for basic testing
- `operator_user` - Operator role for server management testing  
- `admin_user` - Admin role for system-wide testing
- `unapproved_user` - User without approval for testing approval flow

**Database Fixtures:**
- `test_db` - Isolated test database session
- `client` - FastAPI test client with dependency overrides

**Server Fixtures:**
- `test_server` - Basic Minecraft server for testing
- `running_server` - Server in running state for status testing

## Testing Guidelines

### Test Coverage Standards
- Aim for >90% coverage on critical business logic
- Focus on error paths and edge cases
- Test role-based access control thoroughly
- Validate input sanitization and security

### Mock Strategy
- Mock external APIs (Minecraft API, Mojang API)
- Mock file system operations when testing logic
- Use real database operations in integration tests
- Mock subprocess calls for server process testing

### Performance Testing
- Test request/response times for critical endpoints
- Validate database query performance
- Test WebSocket connection handling
- Monitor memory usage in long-running tests

## Configuration

**pytest.ini Configuration:**
```ini
[tool:pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

**Coverage Configuration:**
- Source: `app/` directory
- Excludes: tests, __init__.py files, virtual environments
- Branch coverage enabled
- HTML reports generated in `htmlcov/`

## Best Practices

1. **Test Independence**: Each test should be able to run independently
2. **Database Isolation**: Use test database with cleanup between tests
3. **Authentication Testing**: Test all permission levels for protected endpoints
4. **Error Scenarios**: Test error handling and edge cases
5. **Real-world Data**: Use realistic test data that mirrors production scenarios

## Debugging Tests

**Common Debugging Techniques:**
- Use `-v` flag for verbose output
- Use `-s` flag to see print statements
- Use `pytest.set_trace()` for debugging breakpoints
- Check test database state manually when tests fail
- Review logs in test output for service errors

**Test Database:**
- Test database is isolated and cleaned between runs
- Located at `test.db` (gitignored)
- Schema auto-created from SQLAlchemy models
- Populated with test fixtures as needed