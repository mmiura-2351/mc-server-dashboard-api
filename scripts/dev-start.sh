#!/bin/bash

# Minecraft Server Dashboard API - Development Environment Manager
# This script manages the development environment startup and monitoring

set -euo pipefail

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="mc-dashboard-api"
DEV_PORT="8000"
PID_FILE="/tmp/mc-dashboard-api-dev.pid"
LOG_FILE="/tmp/mc-dashboard-api-dev.log"
REQUIRED_PYTHON_VERSION="3.13"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_dev() {
    echo -e "${MAGENTA}[DEV]${NC} $1"
}

# Error handling
error_exit() {
    log_error "$1"
    cleanup
    exit 1
}

# Cleanup function
cleanup() {
    if [[ -f "$PID_FILE" ]]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping development server (PID: $pid)..."
            kill -TERM "$pid" 2>/dev/null || true

            # Wait for graceful shutdown
            local timeout=10
            while kill -0 "$pid" 2>/dev/null && [[ $timeout -gt 0 ]]; do
                sleep 1
                ((timeout--))
            done

            # Force kill if still running
            if kill -0 "$pid" 2>/dev/null; then
                log_warning "Forcing shutdown..."
                kill -KILL "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$PID_FILE"
    fi
}

# Signal handlers
trap cleanup EXIT INT TERM

# Function to check prerequisites
check_prerequisites() {
    log_info "Checking development environment prerequisites..."

    # Python version is managed by uv - no explicit check needed
    # uv will automatically handle Python version requirements per pyproject.toml

    # Check uv package manager
    if ! command -v uv &> /dev/null; then
        log_warning "uv package manager not found. Installing..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source ~/.bashrc
        export PATH="$HOME/.cargo/bin:$PATH"
        if ! command -v uv &> /dev/null; then
            error_exit "Failed to install uv package manager"
        fi
    fi

    # Check if we're in the project directory
    if [[ ! -f "pyproject.toml" ]] || [[ ! -d "app" ]]; then
        error_exit "Please run this script from the project root directory"
    fi

    # Check port availability
    if lsof -ti:$DEV_PORT >/dev/null 2>&1; then
        local port_process=$(lsof -ti:$DEV_PORT | head -1)
        log_warning "Port $DEV_PORT is already in use by process $port_process"

        # Check if it's our own process
        if [[ -f "$PID_FILE" ]]; then
            local our_pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
            if [[ "$port_process" == "$our_pid" ]]; then
                log_info "Port is being used by our existing development server"
                return 0
            fi
        fi

        log_error "Port conflict detected. Please stop the process using port $DEV_PORT or use a different port"
        echo "Processes using port $DEV_PORT:"
        lsof -i:$DEV_PORT
        exit 1
    fi

    log_success "Prerequisites check completed"
}

# Function to setup development environment
setup_dev_environment() {
    log_info "Setting up development environment..."

    # Install dependencies
    log_info "Installing/updating dependencies..."
    uv sync --group dev

    # Setup environment file if not exists
    if [[ ! -f .env ]]; then
        log_info "Creating development environment file..."
        cp .env.example .env

        # Generate secure SECRET_KEY for development
        local secret_key=$(uv run python -c "import secrets; print(secrets.token_urlsafe(32))")
        sed -i "s/SECRET_KEY=.*/SECRET_KEY=$secret_key/" .env

        log_success "Development .env file created"
    fi

    # Create necessary directories
    mkdir -p servers backups templates file_history logs

    # Create development database if not exists
    if [[ ! -f app.db ]]; then
        log_info "Database will be created on first startup"
    fi

    log_success "Development environment setup completed"
}

# Function to start development server
start_dev_server() {
    log_info "Starting development server..."

    # Check if already running
    if [[ -f "$PID_FILE" ]]; then
        local existing_pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
            log_warning "Development server is already running (PID: $existing_pid)"
            log_info "Use 'kill $existing_pid' to stop it, or delete $PID_FILE if it's stale"
            return 1
        else
            rm -f "$PID_FILE"
        fi
    fi

    # Start the server
    log_dev "Starting FastAPI development server on port $DEV_PORT..."
    log_info "Logs will be written to: $LOG_FILE"
    log_info "PID file: $PID_FILE"

    # Start server with auto-reload
    uv run fastapi dev --host 0.0.0.0 --port "$DEV_PORT" > "$LOG_FILE" 2>&1 &
    local server_pid=$!

    # Save PID
    echo "$server_pid" > "$PID_FILE"

    # Wait for server to start
    log_info "Waiting for server to start..."
    local max_attempts=30
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        if curl -s -f "http://localhost:$DEV_PORT/health" > /dev/null 2>&1; then
            log_success "Development server started successfully!"
            break
        fi

        # Check if process is still running
        if ! kill -0 "$server_pid" 2>/dev/null; then
            log_error "Server process died during startup"
            log_info "Recent logs:"
            tail -20 "$LOG_FILE" 2>/dev/null || echo "No logs available"
            return 1
        fi

        if [[ $attempt -eq $max_attempts ]]; then
            log_error "Server failed to respond after $max_attempts attempts"
            log_info "Recent logs:"
            tail -20 "$LOG_FILE" 2>/dev/null || echo "No logs available"
            cleanup
            return 1
        fi

        sleep 1
        ((attempt++))
    done

    # Display server information
    echo
    echo "=========================================="
    echo "   DEVELOPMENT SERVER STARTED"
    echo "=========================================="
    echo "Server PID: $server_pid"
    echo "API URL: http://localhost:$DEV_PORT"
    echo "Health Check: http://localhost:$DEV_PORT/health"
    echo "API Documentation: http://localhost:$DEV_PORT/docs"
    echo "Alternative Docs: http://localhost:$DEV_PORT/redoc"
    echo "Log File: $LOG_FILE"
    echo "=========================================="
    echo

    log_info "Server is now running with auto-reload enabled"
    log_info "The server will automatically restart when you modify Python files"
    log_warning "Press Ctrl+C to stop the server gracefully"
}

# Function to show server status
show_status() {
    if [[ -f "$PID_FILE" ]]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_success "Development server is running (PID: $pid)"

            # Check API health
            if curl -s -f "http://localhost:$DEV_PORT/health" > /dev/null 2>&1; then
                log_success "API is responding on http://localhost:$DEV_PORT"
            else
                log_warning "Server process exists but API is not responding"
            fi

            # Show recent logs
            echo
            log_info "Recent logs (last 10 lines):"
            tail -10 "$LOG_FILE" 2>/dev/null || echo "No logs available"
        else
            log_warning "PID file exists but process is not running"
            rm -f "$PID_FILE"
        fi
    else
        log_info "Development server is not running"
    fi
}

# Function to view logs
view_logs() {
    local lines=${1:-50}
    local follow=${2:-false}

    if [[ ! -f "$LOG_FILE" ]]; then
        log_warning "Log file not found: $LOG_FILE"
        return 1
    fi

    if [[ "$follow" == "true" ]]; then
        log_info "Following development logs (Press Ctrl+C to exit)..."
        tail -f "$LOG_FILE"
    else
        log_info "Showing last $lines lines of development logs:"
        tail -n "$lines" "$LOG_FILE"
    fi
}

# Function to stop server
stop_server() {
    if [[ -f "$PID_FILE" ]]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping development server (PID: $pid)..."
            cleanup
            log_success "Development server stopped"
        else
            log_warning "PID file exists but process is not running"
            rm -f "$PID_FILE"
        fi
    else
        log_info "Development server is not running"
    fi
}

# Function to show help
show_help() {
    echo "Minecraft Dashboard API Development Environment Manager"
    echo
    echo "Usage: $0 <command> [options]"
    echo
    echo "Commands:"
    echo "  start                     Start development server with auto-reload"
    echo "  stop                      Stop development server"
    echo "  restart                   Restart development server"
    echo "  status                    Show development server status"
    echo "  logs [lines]              View development logs (default: 50 lines)"
    echo "  logs-follow               Follow development logs in real-time"
    echo "  test                      Run test suite"
    echo "  lint                      Run code linting"
    echo "  format                    Format code"
    echo "  help                      Show this help message"
    echo
    echo "Examples:"
    echo "  $0 start                  # Start development server"
    echo "  $0 logs 100               # View last 100 log lines"
    echo "  $0 logs-follow            # Follow logs in real-time"
    echo "  $0 test                   # Run tests"
    echo
    echo "Development URLs:"
    echo "  API: http://localhost:$DEV_PORT"
    echo "  Docs: http://localhost:$DEV_PORT/docs"
    echo "  Health: http://localhost:$DEV_PORT/health"
    echo
}

# Function to run tests
run_tests() {
    log_info "Running test suite..."
    if uv run pytest; then
        log_success "All tests passed!"
    else
        log_error "Some tests failed"
        return 1
    fi
}

# Function to run linting
run_lint() {
    log_info "Running code linting..."
    if uv run ruff check app/; then
        log_success "Linting passed!"
    else
        log_error "Linting issues found"
        return 1
    fi
}

# Function to format code
format_code() {
    log_info "Formatting code..."
    uv run ruff format app/
    log_success "Code formatted!"
}

# Main function
main() {
    local command=${1:-"start"}

    case "$command" in
        "start")
            check_prerequisites
            setup_dev_environment
            start_dev_server

            # Keep script running to monitor the server
            log_info "Monitoring development server... (Press Ctrl+C to stop)"
            while [[ -f "$PID_FILE" ]]; do
                local pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
                if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
                    log_error "Development server process died unexpectedly"
                    log_info "Recent logs:"
                    tail -20 "$LOG_FILE" 2>/dev/null || echo "No logs available"
                    break
                fi
                sleep 5
            done
            ;;
        "stop")
            stop_server
            ;;
        "restart")
            stop_server
            sleep 2
            check_prerequisites
            setup_dev_environment
            start_dev_server
            ;;
        "status")
            show_status
            ;;
        "logs")
            view_logs "${2:-50}" "false"
            ;;
        "logs-follow")
            view_logs "${2:-50}" "true"
            ;;
        "test")
            run_tests
            ;;
        "lint")
            run_lint
            ;;
        "format")
            format_code
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            log_error "Unknown command: $command"
            echo
            show_help
            exit 1
            ;;
    esac
}

# Script execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
