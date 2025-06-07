# API Testing Environment

The `/testing` directory contains tools for testing the Minecraft Server Dashboard API in a client-like environment.

## Testing Tools

### 1. Command Line Testing (`testing/scripts/test_api.sh`)

A comprehensive bash script that tests all major API endpoints:

```bash
cd testing/scripts
./test_api.sh
```

**Features:**
- Automatically starts a dedicated test server on port 8001
- Tests user registration, authentication, and approval flow
- Tests all major API endpoints
- Provides colored output with clear test results
- Automatically cleans up test server and database
- Provides tokens for manual testing

**What it tests:**
- User registration (first user becomes admin)
- User authentication flow
- Admin approval of new users
- Protected endpoints with authentication
- All major API routes (users, servers, groups, templates, backups)

### 2. Browser-based Testing (`testing/web/index.html`)

A web interface for interactive API testing:

```bash
# Open in browser
open testing/web/index.html
# or
firefox testing/web/index.html
```

**Features:**
- User-friendly web interface
- Real-time API testing
- Authentication token management
- Pre-filled test data
- Custom request builder
- JSON response formatting

### 3. Test Server Management (`testing/scripts/test_server.sh`)

Utility script for managing both API and web servers:

```bash
cd testing/scripts
# Main commands (both servers)
./test_server.sh start        # Start both API and web servers
./test_server.sh stop         # Stop both servers and cleanup
./test_server.sh restart      # Restart both servers
./test_server.sh status       # Check status of both servers

# Individual server controls
./test_server.sh start-api    # Start only API server (port 8001)
./test_server.sh start-web    # Start only web server (port 8002)
./test_server.sh stop-api     # Stop only API server
./test_server.sh stop-web     # Stop only web server
```

**Features:**
- **API Server**: Runs on port 8001 (separate from main server on 8000)
- **Web Server**: Python HTTP server on port 8002 for browser testing
- Uses separate test database (`test_app.db`)
- Automatic cleanup on stop
- Process management with PID tracking for both servers

## Server URLs

When servers are running:

- **API Server**: http://localhost:8001/
  - **Swagger UI**: http://localhost:8001/docs
  - **ReDoc**: http://localhost:8001/redoc
- **Web Interface**: http://localhost:8002/

## Example Usage

### Quick API Test
```bash
# Run full test suite
cd testing/scripts
./test_api.sh
```

### Manual Testing
```bash
# Start test server
cd testing/scripts
./test_server.sh start

# Get admin token (from test output)
export ADMIN_TOKEN="your-admin-token-here"

# Test authenticated endpoint
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
     http://localhost:8001/api/v1/users/

# Stop test server
./test_server.sh stop
```

### Browser Testing
1. Start both servers: `cd testing/scripts && ./test_server.sh start`
2. Open web interface: http://localhost:8002/
3. Test API endpoints interactively
4. Stop both servers when done: `cd testing/scripts && ./test_server.sh stop`

## Test Flow

1. **Clean Environment**: Test server starts with fresh database
2. **Admin Creation**: First user automatically gets admin privileges
3. **User Registration**: Regular users require admin approval
4. **Authentication**: JWT tokens for API access
5. **Endpoint Testing**: All major API routes tested
6. **Cleanup**: Automatic cleanup of test environment

## Environment

- **API Test Server**: http://localhost:8001 (auto-created/cleaned database)
- **Web Test Server**: http://localhost:8002 (Python HTTP server)
- **Test Database**: `test_app.db` (auto-created/cleaned)
- **Main Server**: http://localhost:8000 (unaffected)
- **Main Database**: `app.db` (unaffected)

## Security Testing

The test environment safely tests:
- Authentication and authorization
- Role-based access control
- User approval workflow
- Protected endpoint access
- Invalid credential handling

## Notes

- Test environment is completely isolated from production data
- All test data is automatically cleaned up
- No impact on main server or database
- Safe to run repeatedly
- Includes both automated and manual testing options