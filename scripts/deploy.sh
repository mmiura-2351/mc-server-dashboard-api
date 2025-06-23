#!/bin/bash

# Minecraft Server Dashboard API - Production Deployment Script
# This script automates the deployment of the API backend to production

set -euo pipefail

# Color definitions for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
APP_NAME="mc-dashboard-api"
SERVICE_NAME="minecraft-dashboard"
DEPLOY_DIR="/opt/mcs-dashboard/api"
BACKUP_DIR="/backup/mcs-dashboard/api"
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

# Error handling
error_exit() {
    log_error "$1"
    exit 1
}

# Function to check prerequisites
check_prerequisites() {
    log_info "Checking deployment prerequisites..."

    # Check execution privileges - allow both root and sudo users
    if [[ $EUID -eq 0 ]]; then
        log_info "Running as root - deployment will proceed with root privileges"
        SUDO_CMD=""
    else
        # Check sudo privileges for non-root users
        if ! sudo -n true 2>/dev/null; then
            error_exit "This script requires sudo privileges. Please ensure you have sudo access or run as root."
        fi
        log_info "Running as user with sudo privileges"
        SUDO_CMD="sudo"
    fi

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

    # Check Java installation
    if ! command -v java &> /dev/null; then
        log_warning "Java not found. Installing required Java versions..."
        $SUDO_CMD apt update
        $SUDO_CMD apt install -y openjdk-8-jdk openjdk-17-jdk openjdk-21-jdk
    fi

    # Check git
    if ! command -v git &> /dev/null; then
        error_exit "Git is not installed. Please install git."
    fi

    log_success "Prerequisites check completed"
}

# Function to backup existing deployment
backup_deployment() {
    if [[ -d "$DEPLOY_DIR" ]]; then
        log_info "Creating backup of existing deployment..."
        local timestamp=$(date +%Y%m%d_%H%M%S)
        local backup_path="$BACKUP_DIR/pre-deploy-$timestamp"

        $SUDO_CMD mkdir -p "$backup_path"

        # Backup application files
        if [[ -f "$DEPLOY_DIR/app.db" ]]; then
            $SUDO_CMD cp "$DEPLOY_DIR/app.db" "$backup_path/"
            log_info "Database backed up"
        fi

        # Backup important directories
        for dir in servers backups templates file_history; do
            if [[ -d "$DEPLOY_DIR/$dir" ]]; then
                $SUDO_CMD tar -czf "$backup_path/${dir}.tar.gz" -C "$DEPLOY_DIR" "$dir"
                log_info "Directory $dir backed up"
            fi
        done

        # Backup configuration
        if [[ -f "$DEPLOY_DIR/.env" ]]; then
            $SUDO_CMD cp "$DEPLOY_DIR/.env" "$backup_path/"
            log_info "Environment configuration backed up"
        fi

        # Set appropriate ownership for backup files
        if [[ $EUID -eq 0 ]]; then
            # If running as root, keep root ownership but make readable
            chmod -R 755 "$backup_path"
        else
            # If running with sudo, change ownership back to user
            $SUDO_CMD chown -R $USER:$USER "$backup_path"
        fi
        log_success "Backup created at: $backup_path"
    fi
}

# Function to stop existing service
stop_service() {
    log_info "Stopping existing service..."

    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        log_info "Stopping $SERVICE_NAME service..."
        $SUDO_CMD systemctl stop "$SERVICE_NAME"

        # Wait for graceful shutdown
        local timeout=30
        while systemctl is-active --quiet "$SERVICE_NAME" && [[ $timeout -gt 0 ]]; do
            sleep 1
            ((timeout--))
        done

        if systemctl is-active --quiet "$SERVICE_NAME"; then
            log_warning "Service did not stop gracefully, forcing stop..."
            $SUDO_CMD systemctl kill "$SERVICE_NAME"
        fi

        log_success "Service stopped"
    else
        log_info "Service is not running"
    fi
}

# Function to deploy application
deploy_application() {
    log_info "Deploying application to $DEPLOY_DIR..."

    # Create deployment directory
    $SUDO_CMD mkdir -p "$DEPLOY_DIR"

    # Set appropriate ownership
    if [[ $EUID -eq 0 ]]; then
        # If running as root, keep root ownership for security
        log_info "Setting root ownership for deployment directory"
    else
        # If running with sudo, change ownership to user
        $SUDO_CMD chown $USER:$USER "$DEPLOY_DIR"
    fi

    # Clone or update repository
    if [[ -d "$DEPLOY_DIR/.git" ]]; then
        log_info "Updating existing repository..."
        cd "$DEPLOY_DIR"
        git fetch origin
        git reset --hard origin/master
    else
        log_info "Cloning repository..."
        git clone https://github.com/mmiura-2351/mc-server-dashboard-api.git "$DEPLOY_DIR"
        cd "$DEPLOY_DIR"
    fi

    # Install dependencies
    log_info "Installing dependencies..."
    uv sync --frozen

    # Setup environment file
    if [[ ! -f .env ]]; then
        log_info "Creating environment configuration..."
        cp .env.example .env

        # Generate secure SECRET_KEY using uv-managed Python
        local secret_key=$(cd "$DEPLOY_DIR" && uv run python -c "import secrets; print(secrets.token_urlsafe(32))")
        sed -i "s/SECRET_KEY=.*/SECRET_KEY=$secret_key/" .env

        log_warning "Please review and update .env file with your production settings"
    else
        log_info "Environment file already exists, keeping current configuration"
    fi

    # Create necessary directories
    mkdir -p servers backups templates file_history logs

    log_success "Application deployed successfully"
}

# Function to configure systemd service
configure_service() {
    log_info "Configuring systemd service..."

    # Find uv executable path first
    local uv_path=$(which uv 2>/dev/null || echo "")
    if [[ -z "$uv_path" ]]; then
        # Try common installation paths
        for path in /root/.cargo/bin/uv /usr/local/bin/uv ~/.local/bin/uv /home/*/.*cargo/bin/uv; do
            if [[ -x "$path" ]]; then
                uv_path="$path"
                break
            fi
        done
    fi

    if [[ -z "$uv_path" ]]; then
        log_error "uv executable not found. Please ensure uv is installed."
        log_info "Install uv with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        error_exit "uv is required for deployment"
    fi

    log_info "Found uv at: $uv_path"

    # Create service file dynamically with correct uv path
    local service_file="/etc/systemd/system/$SERVICE_NAME.service"
    $SUDO_CMD tee "$service_file" > /dev/null << EOF
[Unit]
Description=Minecraft Dashboard API
Documentation=https://github.com/mmiura-2351/mc-server-dashboard-api
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
# User and Group will be dynamically set during deployment
WorkingDirectory=/opt/mcs-dashboard/api
Environment=PATH=/root/.local/bin:/root/.cargo/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=/opt/mcs-dashboard/api
Environment=NODE_ENV=production
EnvironmentFile=-/opt/mcs-dashboard/api/.env

# Main process
ExecStart=$uv_path run --directory /opt/mcs-dashboard/api uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
ExecReload=/bin/kill -HUP \$MAINPID
ExecStop=/bin/kill -TERM \$MAINPID

# Process management
KillMode=mixed
KillSignal=SIGTERM
TimeoutStartSec=60
TimeoutStopSec=30
Restart=always
RestartSec=10

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=false
RestrictNamespaces=true
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM

# File system restrictions
ReadWritePaths=/opt/mcs-dashboard/api
ReadWritePaths=/opt/mcs-dashboard/api/servers
ReadWritePaths=/opt/mcs-dashboard/api/backups
ReadWritePaths=/opt/mcs-dashboard/api/templates
ReadWritePaths=/opt/mcs-dashboard/api/file_history
ReadWritePaths=/opt/mcs-dashboard/api/logs
ReadWritePaths=/tmp
PrivateTmp=true
PrivateDevices=true

# Network restrictions
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
IPAddressDeny=any
IPAddressAllow=localhost
IPAddressAllow=127.0.0.0/8
IPAddressAllow=::1/128
IPAddressAllow=10.0.0.0/8
IPAddressAllow=172.16.0.0/12
IPAddressAllow=192.168.0.0/16

# Resource limits
LimitNOFILE=65536
LimitNPROC=4096
MemoryMax=2G
TasksMax=4096

# Health check
ExecStartPost=/bin/bash -c 'for i in {1..30}; do if curl -sf http://localhost:8000/health >/dev/null 2>&1; then exit 0; fi; sleep 2; done; exit 1'

[Install]
WantedBy=multi-user.target
EOF

    # Update service file with appropriate user
    if [[ $EUID -eq 0 ]]; then
        # If running as root, set a dedicated service user or root
        log_info "Configuring service to run as root"
        $SUDO_CMD sed -i "/\[Service\]/a User=root" "$service_file"
        $SUDO_CMD sed -i "/User=root/a Group=root" "$service_file"
    else
        # If running with sudo, use current user
        $SUDO_CMD sed -i "/\[Service\]/a User=$USER" "$service_file"
        $SUDO_CMD sed -i "/User=$USER/a Group=$USER" "$service_file"
    fi

    # Reload systemd and enable service
    $SUDO_CMD systemctl daemon-reload
    $SUDO_CMD systemctl enable "$SERVICE_NAME"

    log_success "Service configured and enabled"
}

# Function to start service and validate
start_and_validate() {
    log_info "Starting service and validating deployment..."

    # Start service
    $SUDO_CMD systemctl start "$SERVICE_NAME"

    # Wait for service to start
    sleep 5

    # Check service status
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then
        log_error "Service failed to start. Checking logs..."
        $SUDO_CMD journalctl -u "$SERVICE_NAME" -n 20 --no-pager
        error_exit "Service startup failed"
    fi

    # Health check
    log_info "Performing health check..."
    local max_attempts=30
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        if curl -s -f http://localhost:8000/health > /dev/null 2>&1; then
            log_success "Health check passed"
            break
        fi

        if [[ $attempt -eq $max_attempts ]]; then
            error_exit "Health check failed after $max_attempts attempts"
        fi

        log_info "Waiting for service to be ready... (attempt $attempt/$max_attempts)"
        sleep 2
        ((attempt++))
    done

    # Display service information
    log_success "Deployment completed successfully!"
    echo
    log_info "Service Status:"
    $SUDO_CMD systemctl status "$SERVICE_NAME" --no-pager -l
    echo
    log_info "API Health Check:"
    curl -s http://localhost:8000/health | (cd "$DEPLOY_DIR" && uv run python -m json.tool) 2>/dev/null || echo "API is responding"
    echo
    log_info "Useful commands:"
    if [[ $EUID -eq 0 ]]; then
        echo "  View logs: journalctl -u $SERVICE_NAME -f"
        echo "  Check status: systemctl status $SERVICE_NAME"
        echo "  Restart: systemctl restart $SERVICE_NAME"
        echo "  Stop: systemctl stop $SERVICE_NAME"
    else
        echo "  View logs: sudo journalctl -u $SERVICE_NAME -f"
        echo "  Check status: sudo systemctl status $SERVICE_NAME"
        echo "  Restart: sudo systemctl restart $SERVICE_NAME"
        echo "  Stop: sudo systemctl stop $SERVICE_NAME"
    fi
}

# Function to display deployment summary
deployment_summary() {
    echo
    echo "=========================================="
    echo "   DEPLOYMENT SUMMARY"
    echo "=========================================="
    echo "Service Name: $SERVICE_NAME"
    echo "Deploy Path: $DEPLOY_DIR"
    echo "API URL: http://localhost:8000"
    echo "Health Check: http://localhost:8000/health"
    echo "Documentation: http://localhost:8000/docs"
    echo "=========================================="
    echo
}

# Main deployment function
main() {
    echo "=========================================="
    echo "  Minecraft Dashboard API Deployment"
    echo "=========================================="
    echo

    check_prerequisites
    backup_deployment
    stop_service
    deploy_application
    configure_service
    start_and_validate
    deployment_summary

    log_success "Deployment completed successfully!"
    log_info "The API is now running at http://localhost:8000"
}

# Script execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
