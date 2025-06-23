# Minecraft Server Dashboard API - Makefile
# Provides convenient commands for development and deployment

.PHONY: help install dev dev-start dev-stop dev-status dev-logs test lint format deploy service-start service-stop service-restart service-status service-logs service-enable service-disable clean

# Default target
help:
	@echo "Minecraft Server Dashboard API - Available Commands"
	@echo ""
	@echo "Development Commands:"
	@echo "  make install       - Install dependencies and setup development environment"
	@echo "  make dev           - Start development server"
	@echo "  make dev-start     - Start development server"
	@echo "  make dev-stop      - Stop development server"
	@echo "  make dev-status    - Show development server status"
	@echo "  make dev-logs      - View development logs"
	@echo "  make test          - Run test suite"
	@echo "  make lint          - Run code linting"
	@echo "  make format        - Format code"
	@echo ""
	@echo "Production Commands:"
	@echo "  make deploy        - Deploy to production"
	@echo "  make service-start - Start production service"
	@echo "  make service-stop  - Stop production service"
	@echo "  make service-restart - Restart production service"
	@echo "  make service-status - Show production service status"
	@echo "  make service-logs  - View production service logs"
	@echo "  make service-enable - Enable auto-start on boot"
	@echo "  make service-disable - Disable auto-start on boot"
	@echo ""
	@echo "Utility Commands:"
	@echo "  make clean         - Clean temporary files and caches"
	@echo "  make help          - Show this help message"

# Development commands
install:
	@echo "Installing dependencies and setting up development environment..."
	uv sync --group dev
	uv run pre-commit install
	@echo "Development environment setup complete!"

dev: dev-start

dev-start:
	@echo "Starting development server..."
	./scripts/dev-start.sh start

dev-stop:
	@echo "Stopping development server..."
	./scripts/dev-start.sh stop

dev-status:
	@echo "Checking development server status..."
	./scripts/dev-start.sh status

dev-logs:
	@echo "Viewing development logs..."
	./scripts/dev-start.sh logs

test:
	@echo "Running test suite..."
	uv run pytest

lint:
	@echo "Running code linting..."
	uv run ruff check app/

format:
	@echo "Formatting code..."
	uv run ruff format app/

# Production commands
deploy:
	@echo "Deploying to production..."
	./scripts/deploy.sh

service-start:
	@echo "Starting production service..."
	./scripts/service-manager.sh start

service-stop:
	@echo "Stopping production service..."
	./scripts/service-manager.sh stop

service-restart:
	@echo "Restarting production service..."
	./scripts/service-manager.sh restart

service-status:
	@echo "Checking production service status..."
	./scripts/service-manager.sh status

service-logs:
	@echo "Viewing production service logs..."
	./scripts/service-manager.sh logs

service-enable:
	@echo "Enabling auto-start on boot..."
	./scripts/service-manager.sh enable

service-disable:
	@echo "Disabling auto-start on boot..."
	./scripts/service-manager.sh disable

# Utility commands
clean:
	@echo "Cleaning temporary files and caches..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + || true
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf /tmp/mc-dashboard-api-dev.pid
	rm -rf /tmp/mc-dashboard-api-dev.log
	@echo "Cleanup complete!"
