#!/bin/bash

# Test Server Management Script
# This script manages a separate test server instance

TEST_PORT=8001
WEB_PORT=8002
TEST_DB="test_app.db"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_PID_FILE="$SCRIPT_DIR/test_server.pid"
WEB_PID_FILE="$SCRIPT_DIR/web_server.pid"
SERVERS_BACKUP_DIR="$SCRIPT_DIR/servers_backup"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

backup_servers_directory() {
    # Get project root directory (two levels up from scripts/)
    PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
    
    # Check if servers directory exists
    if [ -d "$PROJECT_ROOT/servers" ]; then
        print_info "Backing up existing servers directory..."
        # Remove old backup if it exists
        if [ -d "$SERVERS_BACKUP_DIR" ]; then
            rm -rf "$SERVERS_BACKUP_DIR"
        fi
        # Create backup
        mv "$PROJECT_ROOT/servers" "$SERVERS_BACKUP_DIR"
        print_info "Servers directory backed up to scripts/servers_backup"
    fi
    
    # Create empty servers directory for testing
    mkdir -p "$PROJECT_ROOT/servers"
}

restore_servers_directory() {
    # Get project root directory (two levels up from scripts/)
    PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
    
    # Remove test servers directory
    if [ -d "$PROJECT_ROOT/servers" ]; then
        rm -rf "$PROJECT_ROOT/servers"
        print_info "Test servers directory cleaned up"
    fi
    
    # Restore original servers directory if backup exists
    if [ -d "$SERVERS_BACKUP_DIR" ]; then
        mv "$SERVERS_BACKUP_DIR" "$PROJECT_ROOT/servers"
        print_info "Original servers directory restored"
    fi
}

start_test_server() {
    # Check if test server is already running
    if [ -f "$SERVER_PID_FILE" ]; then
        PID=$(cat "$SERVER_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            print_warning "Test server is already running (PID: $PID) on port $TEST_PORT"
            return 0
        else
            rm -f "$SERVER_PID_FILE"
        fi
    fi
    
    print_info "Starting test server on port $TEST_PORT..."
    
    # Get project root directory (two levels up from scripts/)
    PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
    cd "$PROJECT_ROOT"
    
    # Backup existing servers directory and create clean test environment
    backup_servers_directory
    
    # Set test database URL
    export DATABASE_URL="sqlite:///./$TEST_DB"
    
    # Start server in background
    nohup uv run fastapi dev --host 0.0.0.0 --port $TEST_PORT > "$SCRIPT_DIR/test_server.log" 2>&1 &
    SERVER_PID=$!
    
    # Save PID for later cleanup
    echo $SERVER_PID > "$SERVER_PID_FILE"
    
    # Wait for server to start
    print_info "Waiting for test server to start..."
    sleep 5
    
    # Check if server is running
    if ps -p "$SERVER_PID" > /dev/null 2>&1; then
        if curl -s "http://localhost:$TEST_PORT/docs" > /dev/null; then
            print_success "Test server started successfully (PID: $SERVER_PID)"
            print_info "API Documentation: http://localhost:$TEST_PORT/docs"
            print_info "Test database: $TEST_DB"
            return 0
        else
            print_error "Test server started but not responding"
            return 1
        fi
    else
        print_error "Failed to start test server"
        return 1
    fi
}

stop_test_server() {
    if [ -f "$SERVER_PID_FILE" ]; then
        PID=$(cat "$SERVER_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            print_info "Stopping test server (PID: $PID)..."
            kill $PID
            sleep 2
            
            # Force kill if still running
            if ps -p "$PID" > /dev/null 2>&1; then
                print_warning "Force killing test server..."
                kill -9 $PID
            fi
            
            print_success "Test server stopped"
        else
            print_warning "Test server not running (stale PID file)"
        fi
        rm -f "$SERVER_PID_FILE"
    else
        print_warning "No test server PID file found"
    fi
    
    # Clean up test database (from project root)
    PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
    if [ -f "$PROJECT_ROOT/$TEST_DB" ]; then
        rm -f "$PROJECT_ROOT/$TEST_DB"
        print_info "Test database cleaned up"
    fi
    
    # Restore original servers directory
    restore_servers_directory
    
    # Clean up log file
    if [ -f "$SCRIPT_DIR/test_server.log" ]; then
        rm -f "$SCRIPT_DIR/test_server.log"
        print_info "Test server log cleaned up"
    fi
}

start_web_server() {
    # Check if web server is already running
    if [ -f "$WEB_PID_FILE" ]; then
        PID=$(cat "$WEB_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            print_warning "Web server is already running (PID: $PID) on port $WEB_PORT"
            return 0
        else
            rm -f "$WEB_PID_FILE"
        fi
    fi
    
    print_info "Starting web server on port $WEB_PORT..."
    
    # Get web directory path (one level up from scripts/)
    WEB_DIR="$SCRIPT_DIR/../web"
    
    # Start Python HTTP server in background
    cd "$WEB_DIR"
    nohup python3 -m http.server $WEB_PORT > "$SCRIPT_DIR/web_server.log" 2>&1 &
    WEB_PID=$!
    
    # Save PID for later cleanup
    echo $WEB_PID > "$WEB_PID_FILE"
    
    # Wait for server to start
    print_info "Waiting for web server to start..."
    sleep 2
    
    # Check if server is running
    if ps -p "$WEB_PID" > /dev/null 2>&1; then
        if curl -s "http://localhost:$WEB_PORT/" > /dev/null; then
            print_success "Web server started successfully (PID: $WEB_PID)"
            print_info "Web interface: http://localhost:$WEB_PORT/"
            return 0
        else
            print_error "Web server started but not responding"
            return 1
        fi
    else
        print_error "Failed to start web server"
        return 1
    fi
}

stop_web_server() {
    if [ -f "$WEB_PID_FILE" ]; then
        PID=$(cat "$WEB_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            print_info "Stopping web server (PID: $PID)..."
            kill $PID
            sleep 2
            
            # Force kill if still running
            if ps -p "$PID" > /dev/null 2>&1; then
                print_warning "Force killing web server..."
                kill -9 $PID
            fi
            
            print_success "Web server stopped"
        else
            print_warning "Web server not running (stale PID file)"
        fi
        rm -f "$WEB_PID_FILE"
    else
        print_warning "No web server PID file found"
    fi
    
    # Clean up web log file
    if [ -f "$SCRIPT_DIR/web_server.log" ]; then
        rm -f "$SCRIPT_DIR/web_server.log"
        print_info "Web server log cleaned up"
    fi
}

start_both_servers() {
    print_info "Starting both API and web servers..."
    start_test_server
    if [ $? -eq 0 ]; then
        start_web_server
        if [ $? -eq 0 ]; then
            echo ""
            print_success "Both servers started successfully!"
            print_info "API Server: http://localhost:$TEST_PORT/docs"
            print_info "Web Interface: http://localhost:$WEB_PORT/"
        else
            print_error "Failed to start web server"
            return 1
        fi
    else
        print_error "Failed to start API server"
        return 1
    fi
}

stop_both_servers() {
    print_info "Stopping both servers..."
    stop_test_server
    stop_web_server
    print_success "Both servers stopped"
}

status_test_server() {
    echo "=== API Server Status ==="
    if [ -f "$SERVER_PID_FILE" ]; then
        PID=$(cat "$SERVER_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            print_success "API server is running (PID: $PID) on port $TEST_PORT"
            if curl -s "http://localhost:$TEST_PORT/docs" > /dev/null; then
                print_success "API server is responding to requests"
            else
                print_error "API server is running but not responding"
            fi
        else
            print_error "API server is not running (stale PID file)"
            rm -f "$SERVER_PID_FILE"
        fi
    else
        print_warning "API server is not running"
    fi
    
    echo ""
    echo "=== Web Server Status ==="
    if [ -f "$WEB_PID_FILE" ]; then
        PID=$(cat "$WEB_PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            print_success "Web server is running (PID: $PID) on port $WEB_PORT"
            if curl -s "http://localhost:$WEB_PORT/" > /dev/null; then
                print_success "Web server is responding to requests"
            else
                print_error "Web server is running but not responding"
            fi
        else
            print_error "Web server is not running (stale PID file)"
            rm -f "$WEB_PID_FILE"
        fi
    else
        print_warning "Web server is not running"
    fi
}

case "$1" in
    start)
        start_both_servers
        ;;
    stop)
        stop_both_servers
        ;;
    restart)
        stop_both_servers
        sleep 1
        start_both_servers
        ;;
    start-api)
        start_test_server
        ;;
    stop-api)
        stop_test_server
        ;;
    restart-api)
        stop_test_server
        sleep 1
        start_test_server
        ;;
    start-web)
        start_web_server
        ;;
    stop-web)
        stop_web_server
        ;;
    restart-web)
        stop_web_server
        sleep 1
        start_web_server
        ;;
    start-both)
        start_both_servers
        ;;
    stop-both)
        stop_both_servers
        ;;
    restart-both)
        stop_both_servers
        sleep 1
        start_both_servers
        ;;
    status)
        status_test_server
        ;;
    *)
        echo "Usage: $0 {COMMAND}"
        echo ""
        echo "Main Commands:"
        echo "  start        - Start both API and web servers"
        echo "  stop         - Stop both servers and clean up"
        echo "  restart      - Restart both servers"
        echo ""
        echo "Individual API Server Commands:"
        echo "  start-api    - Start only API test server on port $TEST_PORT"
        echo "  stop-api     - Stop only API test server"
        echo "  restart-api  - Restart only API test server"
        echo ""
        echo "Web Server Commands:"
        echo "  start-web    - Start web server on port $WEB_PORT"
        echo "  stop-web     - Stop web server and clean up"
        echo "  restart-web  - Restart web server"
        echo ""
        echo "Combined Commands:"
        echo "  start-both   - Start both API and web servers"
        echo "  stop-both    - Stop both servers and clean up"
        echo "  restart-both - Restart both servers"
        echo ""
        echo "Status Commands:"
        echo "  status       - Check status of both servers"
        echo ""
        echo "API Server Info:"
        echo "  - Uses separate database: $TEST_DB"
        echo "  - Uses isolated servers directory (backed up to scripts/servers_backup)"
        echo "  - API Documentation: http://localhost:$TEST_PORT/docs"
        echo "  - ReDoc: http://localhost:$TEST_PORT/redoc"
        echo ""
        echo "Web Server Info:"
        echo "  - Serves testing web interface"
        echo "  - Web Interface: http://localhost:$WEB_PORT/"
        exit 1
        ;;
esac