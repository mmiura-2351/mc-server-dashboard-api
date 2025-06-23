#!/bin/bash

# Minecraft Server Dashboard API - Service Manager
# This script provides comprehensive service lifecycle management

set -euo pipefail

# Color definitions
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="minecraft-dashboard"
API_URL="http://localhost:8000"
HEALTH_ENDPOINT="$API_URL/health"

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

log_status() {
    echo -e "${CYAN}[STATUS]${NC} $1"
}

# Function to check service status
check_service_status() {
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        return 0  # Service is active
    else
        return 1  # Service is not active
    fi
}

# Function to check API health
check_api_health() {
    if curl -s -f "$HEALTH_ENDPOINT" > /dev/null 2>&1; then
        return 0  # API is healthy
    else
        return 1  # API is not responding
    fi
}

# Function to display detailed status
show_status() {
    echo "=========================================="
    echo "   MINECRAFT DASHBOARD API STATUS"
    echo "=========================================="
    echo

    # Service status
    log_info "Service Status:"
    if check_service_status; then
        log_success "Service is ACTIVE"

        # Detailed systemd status
        echo
        sudo systemctl status "$SERVICE_NAME" --no-pager -l | head -20

        # API health check
        echo
        log_info "API Health Check:"
        if check_api_health; then
            log_success "API is HEALTHY and responding"

            # Try to get health details
            local health_response=$(curl -s "$HEALTH_ENDPOINT" 2>/dev/null || echo '{"status": "unknown"}')
            echo "Health Response: $health_response" | python3 -m json.tool 2>/dev/null || echo "$health_response"
        else
            log_warning "API is NOT responding on $API_URL"
            log_info "This might indicate a startup issue or port conflict"
        fi

        # Port check
        echo
        log_info "Port Information:"
        local port_info=$(sudo netstat -tlnp | grep :8000 || echo "Port 8000 not found")
        echo "$port_info"

    else
        log_error "Service is INACTIVE"
        echo
        log_info "Recent service logs:"
        sudo journalctl -u "$SERVICE_NAME" -n 10 --no-pager
    fi

    # Service configuration
    echo
    log_info "Service Configuration:"
    echo "Service Name: $SERVICE_NAME"
    echo "API URL: $API_URL"
    echo "Health Endpoint: $HEALTH_ENDPOINT"
    echo "Service File: /etc/systemd/system/$SERVICE_NAME.service"

    # Enable status
    echo
    log_info "Auto-start Status:"
    if systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
        log_success "Service is ENABLED (will start automatically on boot)"
    else
        log_warning "Service is DISABLED (will not start automatically on boot)"
    fi

    echo "=========================================="
}

# Function to start service
start_service() {
    log_info "Starting $SERVICE_NAME service..."

    if check_service_status; then
        log_warning "Service is already running"
        return 0
    fi

    # Start the service
    sudo systemctl start "$SERVICE_NAME"

    # Wait for startup
    log_info "Waiting for service to start..."
    local timeout=30
    local count=0

    while [[ $count -lt $timeout ]]; do
        if check_service_status; then
            log_success "Service started successfully"

            # Wait a bit more for API to be ready
            log_info "Waiting for API to be ready..."
            sleep 3

            if check_api_health; then
                log_success "API is now responding"
            else
                log_warning "Service started but API is not yet responding"
                log_info "This is normal during startup. Check logs if it persists."
            fi

            return 0
        fi

        sleep 1
        ((count++))
    done

    log_error "Service failed to start within $timeout seconds"
    log_info "Checking logs for errors..."
    sudo journalctl -u "$SERVICE_NAME" -n 20 --no-pager
    return 1
}

# Function to stop service
stop_service() {
    log_info "Stopping $SERVICE_NAME service..."

    if ! check_service_status; then
        log_warning "Service is already stopped"
        return 0
    fi

    # Stop the service
    sudo systemctl stop "$SERVICE_NAME"

    # Wait for shutdown
    log_info "Waiting for service to stop..."
    local timeout=30
    local count=0

    while [[ $count -lt $timeout ]]; do
        if ! check_service_status; then
            log_success "Service stopped successfully"
            return 0
        fi

        sleep 1
        ((count++))
    done

    log_warning "Service did not stop gracefully, forcing stop..."
    sudo systemctl kill "$SERVICE_NAME"
    sleep 2

    if ! check_service_status; then
        log_success "Service stopped forcefully"
    else
        log_error "Failed to stop service"
        return 1
    fi
}

# Function to restart service
restart_service() {
    log_info "Restarting $SERVICE_NAME service..."

    stop_service
    sleep 2
    start_service
}

# Function to reload service configuration
reload_service() {
    log_info "Reloading $SERVICE_NAME service configuration..."

    if ! check_service_status; then
        log_error "Service is not running. Use 'start' command instead."
        return 1
    fi

    # Send HUP signal for graceful reload
    sudo systemctl reload "$SERVICE_NAME"

    log_info "Reload signal sent. Checking API health..."
    sleep 3

    if check_api_health; then
        log_success "Service reloaded successfully"
    else
        log_warning "Reload completed but API is not responding"
        log_info "Check logs for any issues"
    fi
}

# Function to view logs
view_logs() {
    local lines=${1:-50}
    local follow=${2:-false}

    log_info "Viewing service logs (last $lines lines)..."

    if [[ "$follow" == "true" ]]; then
        log_info "Following logs (Press Ctrl+C to exit)..."
        sudo journalctl -u "$SERVICE_NAME" -n "$lines" -f
    else
        sudo journalctl -u "$SERVICE_NAME" -n "$lines" --no-pager
    fi
}

# Function to enable/disable auto-start
toggle_autostart() {
    local action=${1:-""}

    case "$action" in
        "enable")
            log_info "Enabling auto-start for $SERVICE_NAME..."
            sudo systemctl enable "$SERVICE_NAME"
            log_success "Auto-start enabled"
            ;;
        "disable")
            log_info "Disabling auto-start for $SERVICE_NAME..."
            sudo systemctl disable "$SERVICE_NAME"
            log_success "Auto-start disabled"
            ;;
        *)
            log_error "Invalid action. Use 'enable' or 'disable'"
            return 1
            ;;
    esac
}

# Function to show help
show_help() {
    echo "Minecraft Dashboard API Service Manager"
    echo
    echo "Usage: $0 <command> [options]"
    echo
    echo "Commands:"
    echo "  status                    Show detailed service status"
    echo "  start                     Start the service"
    echo "  stop                      Stop the service"
    echo "  restart                   Restart the service"
    echo "  reload                    Reload service configuration"
    echo "  logs [lines]              View service logs (default: 50 lines)"
    echo "  logs-follow [lines]       Follow service logs in real-time"
    echo "  enable                    Enable auto-start on boot"
    echo "  disable                   Disable auto-start on boot"
    echo "  help                      Show this help message"
    echo
    echo "Examples:"
    echo "  $0 status                 # Show current status"
    echo "  $0 start                  # Start the service"
    echo "  $0 logs 100               # View last 100 log lines"
    echo "  $0 logs-follow            # Follow logs in real-time"
    echo
}

# Main function
main() {
    local command=${1:-"status"}

    case "$command" in
        "status")
            show_status
            ;;
        "start")
            start_service
            ;;
        "stop")
            stop_service
            ;;
        "restart")
            restart_service
            ;;
        "reload")
            reload_service
            ;;
        "logs")
            view_logs "${2:-50}" "false"
            ;;
        "logs-follow")
            view_logs "${2:-50}" "true"
            ;;
        "enable")
            toggle_autostart "enable"
            ;;
        "disable")
            toggle_autostart "disable"
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
