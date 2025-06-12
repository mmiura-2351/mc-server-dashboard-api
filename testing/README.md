# API Testing Tools

This directory contains tools for testing the Minecraft Server Dashboard API in a client-like environment.

## Directory Structure

```
testing/
├── scripts/           # Command-line testing scripts
│   ├── test_api.sh   # Comprehensive API test suite
│   └── test_server.sh # Test server management
├── web/              # Browser-based testing tools
│   └── index.html    # Interactive API testing interface
└── README.md         # This file
```

## Quick Start

### Command Line Testing
```bash
# Run comprehensive test suite
cd testing/scripts
./test_api.sh
```

### Browser Testing
```bash
# Start both API and web servers
cd testing/scripts
./test_server.sh start

# Web interface automatically available at:
# http://localhost:8002/

# Stop both servers when done
./test_server.sh stop
```

### Test Server Management
```bash
cd testing/scripts

# Main commands (both servers)
./test_server.sh start     # Start both API and web servers
./test_server.sh stop      # Stop both servers and cleanup
./test_server.sh restart   # Restart both servers
./test_server.sh status    # Check status of both servers

# Individual server controls
./test_server.sh start-api    # Start only API server (port 8001)
./test_server.sh start-web    # Start only web server (port 8002)
./test_server.sh stop-api     # Stop only API server
./test_server.sh stop-web     # Stop only web server
```

## Features

- **Isolated Testing**: Uses separate test server (port 8001) and database
- **Integrated Web Interface**: Python-hosted web server (port 8002) for browser testing
- **Comprehensive Coverage**: Tests authentication, authorization, and all major endpoints
- **Multiple Interfaces**: Command-line and web-based testing
- **Automatic Cleanup**: No impact on production data
- **Easy Setup**: One-command starts both API and web servers
- **Screenshot Evidence**: Browser tests can capture visual evidence saved to `../screenshots/{timestamp}/`

## Documentation

For detailed documentation, see: [docs/testing.md](../docs/testing.md)

## Server URLs

When servers are running:
- **API Server**: http://localhost:8001/
  - Swagger UI: http://localhost:8001/docs
  - ReDoc: http://localhost:8001/redoc
- **Web Interface**: http://localhost:8002/