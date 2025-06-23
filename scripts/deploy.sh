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

    # Check if running as root
    if [[ $EUID -eq 0 ]]; then
        error_exit "This script should not be run as root. Please run as a regular user with sudo privileges."
    fi

    # Check sudo privileges
    if ! sudo -n true 2>/dev/null; then
        error_exit "This script requires sudo privileges. Please ensure you have sudo access."
    fi

    # Check Python version
    if ! command -v python3 &> /dev/null; then
        error_exit "Python 3 is not installed. Please install Python ${REQUIRED_PYTHON_VERSION}+"
    fi

    local python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)" 2>/dev/null; then
        error_exit "Python ${REQUIRED_PYTHON_VERSION}+ is required. Current version: ${python_version}"
    fi

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
        sudo apt update
        sudo apt install -y openjdk-8-jdk openjdk-17-jdk openjdk-21-jdk
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

        sudo mkdir -p "$backup_path"

        # Backup application files
        if [[ -f "$DEPLOY_DIR/app.db" ]]; then
            sudo cp "$DEPLOY_DIR/app.db" "$backup_path/"
            log_info "Database backed up"
        fi

        # Backup important directories
        for dir in servers backups templates file_history; do
            if [[ -d "$DEPLOY_DIR/$dir" ]]; then
                sudo tar -czf "$backup_path/${dir}.tar.gz" -C "$DEPLOY_DIR" "$dir"
                log_info "Directory $dir backed up"
            fi
        done

        # Backup configuration
        if [[ -f "$DEPLOY_DIR/.env" ]]; then
            sudo cp "$DEPLOY_DIR/.env" "$backup_path/"
            log_info "Environment configuration backed up"
        fi

        sudo chown -R $USER:$USER "$backup_path"
        log_success "Backup created at: $backup_path"
    fi
}

# Function to stop existing service
stop_service() {
    log_info "Stopping existing service..."

    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        log_info "Stopping $SERVICE_NAME service..."
        sudo systemctl stop "$SERVICE_NAME"

        # Wait for graceful shutdown
        local timeout=30
        while systemctl is-active --quiet "$SERVICE_NAME" && [[ $timeout -gt 0 ]]; do
            sleep 1
            ((timeout--))
        done

        if systemctl is-active --quiet "$SERVICE_NAME"; then
            log_warning "Service did not stop gracefully, forcing stop..."
            sudo systemctl kill "$SERVICE_NAME"
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
    sudo mkdir -p "$DEPLOY_DIR"
    sudo chown $USER:$USER "$DEPLOY_DIR"

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

        # Generate secure SECRET_KEY
        local secret_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
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

    # Copy and configure service file
    local service_file="/etc/systemd/system/$SERVICE_NAME.service"
    sudo cp "$DEPLOY_DIR/deployment/minecraft-dashboard.service" "$service_file"

    # Update service file with current user
    sudo sed -i "/\[Service\]/a User=$USER" "$service_file"
    sudo sed -i "/User=$USER/a Group=$USER" "$service_file"

    # Reload systemd and enable service
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"

    log_success "Service configured and enabled"
}

# Function to start service and validate
start_and_validate() {
    log_info "Starting service and validating deployment..."

    # Start service
    sudo systemctl start "$SERVICE_NAME"

    # Wait for service to start
    sleep 5

    # Check service status
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then
        log_error "Service failed to start. Checking logs..."
        sudo journalctl -u "$SERVICE_NAME" -n 20 --no-pager
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
    sudo systemctl status "$SERVICE_NAME" --no-pager -l
    echo
    log_info "API Health Check:"
    curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "API is responding"
    echo
    log_info "Useful commands:"
    echo "  View logs: sudo journalctl -u $SERVICE_NAME -f"
    echo "  Check status: sudo systemctl status $SERVICE_NAME"
    echo "  Restart: sudo systemctl restart $SERVICE_NAME"
    echo "  Stop: sudo systemctl stop $SERVICE_NAME"
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
