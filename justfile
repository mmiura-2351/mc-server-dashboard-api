# Minecraft Server Dashboard API - justfile
# Task runner recipes. Run `just` (no args) to see the list.

# Default: show available recipes
default:
    @just --list

# --- Development ------------------------------------------------------------

# Install dependencies and setup development environment
install:
    uv sync --group dev
    uv run pre-commit install

# Start development server (alias of dev-start)
dev: dev-start

# Start development server with monitoring
dev-start:
    ./scripts/dev-start.sh start

# Stop development server
dev-stop:
    ./scripts/dev-start.sh stop

# Show development server status
dev-status:
    ./scripts/dev-start.sh status

# View development logs
dev-logs:
    ./scripts/dev-start.sh logs

# Run test suite
test:
    uv run pytest

# Run test suite with coverage report
coverage:
    uv run pytest --cov=app --cov-branch --cov-report=term-missing --cov-report=html

# Run code linting (ruff check)
lint:
    uv run ruff check app/

# Verify code formatting without writing changes (ruff format --check)
format-check:
    uv run ruff format app/ --check

# Format code (ruff format)
format:
    uv run ruff format app/

# --- Production -------------------------------------------------------------

# Deploy to production
deploy:
    ./scripts/deploy.sh

# Start production service
service-start:
    ./scripts/service-manager.sh start

# Stop production service
service-stop:
    ./scripts/service-manager.sh stop

# Restart production service
service-restart:
    ./scripts/service-manager.sh restart

# Show production service status
service-status:
    ./scripts/service-manager.sh status

# View production service logs
service-logs:
    ./scripts/service-manager.sh logs

# Enable auto-start on boot
service-enable:
    ./scripts/service-manager.sh enable

# Disable auto-start on boot
service-disable:
    ./scripts/service-manager.sh disable

# --- Utility ----------------------------------------------------------------

# Clean temporary files and caches
clean:
    find . -type f -name "*.pyc" -delete
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type d -name "*.egg-info" -exec rm -rf {} +
    rm -rf .pytest_cache/
    rm -rf htmlcov/
    rm -rf .coverage
    rm -f /tmp/mc-dashboard-api-dev.pid
    rm -f /tmp/mc-dashboard-api-dev.log
