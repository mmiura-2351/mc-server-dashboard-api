# Minecraft Server Dashboard API - Comprehensive Deployment Guide

This guide provides complete instructions for deploying the Minecraft Server Dashboard API in production environments.

## Table of Contents

1. [Quick Deployment](#quick-deployment)
2. [Prerequisites](#prerequisites)
3. [Production Deployment](#production-deployment)
4. [Nginx Reverse Proxy Setup](#nginx-reverse-proxy-setup)
5. [Security Configuration](#security-configuration)
6. [Monitoring and Maintenance](#monitoring-and-maintenance)
7. [Troubleshooting](#troubleshooting)
8. [Development Environment](#development-environment)

## Quick Deployment

For a rapid production deployment:

```bash
# Clone repository and run automated deployment
git clone https://github.com/mmiura-2351/mc-server-dashboard-api.git
cd mc-server-dashboard-api
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

The deployment script will:
- Validate prerequisites and install missing components
- Create secure configurations with auto-generated secrets
- Deploy the application to `/opt/mcs-dashboard/api`
- Configure and start the systemd service
- Perform health checks and validation

## Prerequisites

### System Requirements

- **Operating System**: Ubuntu 20.04+ or similar Linux distribution
- **uv package manager**: Automatically handles Python 3.13+ requirement
- **Memory**: Minimum 2GB RAM (4GB+ recommended for multiple servers)
- **Disk Space**: 10GB+ (depends on number of Minecraft servers and backups)
- **Network**: Open ports for API (8000) and Minecraft servers (25565+)

### Required Software

```bash
# Update package manager
sudo apt update

# Install essential packages
sudo apt install -y curl git build-essential

# Install Java (multiple versions for Minecraft compatibility)
sudo apt install -y openjdk-8-jdk openjdk-17-jdk openjdk-21-jdk

# Install uv package manager (handles Python automatically)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

### Network Configuration

```bash
# Configure firewall (if using ufw)
sudo ufw allow 8000/tcp comment "Minecraft Dashboard API"
sudo ufw allow 25565:25600/tcp comment "Minecraft Servers"
sudo ufw reload

# For nginx reverse proxy (optional)
sudo ufw allow 80/tcp comment "HTTP"
sudo ufw allow 443/tcp comment "HTTPS"
```

## Production Deployment

### Automated Deployment

The easiest way to deploy is using the provided deployment script:

```bash
# Make deployment script executable
chmod +x scripts/deploy.sh

# Run deployment (requires sudo privileges)
./scripts/deploy.sh
```

### Manual Deployment

If you prefer manual deployment or need customization:

#### 1. Create Deployment Directory

```bash
sudo mkdir -p /opt/mcs-dashboard/api
sudo chown $USER:$USER /opt/mcs-dashboard/api
cd /opt/mcs-dashboard/api/api
```

#### 2. Clone and Setup Application

```bash
# Clone repository
git clone https://github.com/mmiura-2351/mc-server-dashboard-api.git .

# Install dependencies
uv sync --frozen

# Create environment configuration
cp .env.example .env
```

#### 3. Configure Environment Variables

Edit `/opt/mcs-dashboard/api/.env`:

```bash
# Security (REQUIRED - generate secure key)
SECRET_KEY=your-cryptographically-secure-key-here

# Database
DATABASE_URL=sqlite:///./app.db

# Authentication
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Application
ENVIRONMENT=production

# Java Paths (auto-detected if not specified)
JAVA_8_PATH=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
JAVA_17_PATH=/usr/lib/jvm/java-17-openjdk-amd64/bin/java
JAVA_21_PATH=/usr/lib/jvm/java-21-openjdk-amd64/bin/java

# Logging
LOG_LEVEL=INFO
```

**Important**: Generate a secure SECRET_KEY:
```bash
uv run python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"
```

#### 4. Configure Systemd Service

```bash
# Copy service file
sudo cp deployment/minecraft-dashboard.service /etc/systemd/system/

# Update service file with current user
sudo sed -i "/\[Service\]/a User=$USER" /etc/systemd/system/minecraft-dashboard.service
sudo sed -i "/User=$USER/a Group=$USER" /etc/systemd/system/minecraft-dashboard.service

# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable minecraft-dashboard
sudo systemctl start minecraft-dashboard
```

#### 5. Verify Deployment

```bash
# Check service status
sudo systemctl status minecraft-dashboard

# Verify API health
curl http://localhost:8000/api/v1/health

# View logs
sudo journalctl -u minecraft-dashboard -f
```

## Nginx Reverse Proxy Setup

For production environments, it's recommended to use nginx as a reverse proxy for SSL termination and improved security.

### Install and Configure Nginx

```bash
# Install nginx
sudo apt install -y nginx

# Create configuration file
sudo vim /etc/nginx/sites-available/minecraft-dashboard
```

### Nginx Configuration

```nginx
# /etc/nginx/sites-available/minecraft-dashboard
server {
    listen 80;
    server_name your-domain.com;  # Replace with your domain

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;  # Replace with your domain

    # SSL Configuration (replace with your certificate paths)
    ssl_certificate /etc/ssl/certs/your-cert.pem;
    ssl_certificate_key /etc/ssl/private/your-key.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:50m;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Security headers
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
    add_header Referrer-Policy "strict-origin-when-cross-origin";
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws: wss:; font-src 'self'";

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req zone=api burst=20 nodelay;

    # Main API proxy
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 86400;

        # WebSocket support for real-time features
        proxy_set_header Sec-WebSocket-Extensions $http_sec_websocket_extensions;
        proxy_set_header Sec-WebSocket-Key $http_sec_websocket_key;
        proxy_set_header Sec-WebSocket-Protocol $http_sec_websocket_protocol;
        proxy_set_header Sec-WebSocket-Version $http_sec_websocket_version;
    }

    # Health check endpoint (bypass rate limiting)
    location /api/v1/health {
        proxy_pass http://127.0.0.1:8000;
        access_log off;
    }

    # Static file serving (if needed)
    location /static/ {
        alias /opt/mcs-dashboard/api/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Logging
    access_log /var/log/nginx/minecraft-dashboard.access.log;
    error_log /var/log/nginx/minecraft-dashboard.error.log;
}
```

### Enable Nginx Configuration

```bash
# Enable site
sudo ln -s /etc/nginx/sites-available/minecraft-dashboard /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx

# Enable nginx auto-start
sudo systemctl enable nginx
```

### SSL Certificate Setup

For production, obtain SSL certificates from Let's Encrypt:

```bash
# Install certbot
sudo apt install -y certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal
sudo systemctl enable certbot.timer
```

## Security Configuration

### Firewall Configuration

```bash
# Configure UFW firewall
sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow SSH
sudo ufw allow ssh

# Allow nginx
sudo ufw allow 'Nginx Full'

# Allow Minecraft server ports
sudo ufw allow 25565:25600/tcp

# Enable firewall
sudo ufw --force enable
```

### Application Security

The systemd service includes comprehensive security hardening:

- **Process isolation**: NoNewPrivileges, ProtectSystem, ProtectHome
- **Network restrictions**: Limited address families and IP ranges
- **File system protection**: Read-only system directories, private /tmp
- **Resource limits**: Memory, CPU, and file descriptor limits
- **System call filtering**: Restricted to essential system calls

### Database Security

```bash
# Secure SQLite database file
chmod 600 /opt/mcs-dashboard/api/app.db
chown $USER:$USER /opt/mcs-dashboard/api/app.db
```

## Monitoring and Maintenance

### Service Management

Use the provided service manager script for easy management:

```bash
# Check service status
./scripts/service-manager.sh status

# Start/stop/restart service
./scripts/service-manager.sh start
./scripts/service-manager.sh stop
./scripts/service-manager.sh restart

# View logs
./scripts/service-manager.sh logs
./scripts/service-manager.sh logs-follow

# Enable/disable auto-start
./scripts/service-manager.sh enable
./scripts/service-manager.sh disable
```

### Health Monitoring

```bash
# API health check
curl http://localhost:8000/api/v1/health

# Service health check
./scripts/service-manager.sh status

# System resource monitoring
htop
df -h
```

### Log Management

```bash
# View application logs
sudo journalctl -u minecraft-dashboard -f

# View nginx logs (if using nginx)
sudo tail -f /var/log/nginx/minecraft-dashboard.access.log
sudo tail -f /var/log/nginx/minecraft-dashboard.error.log

# Rotate logs automatically
sudo logrotate -f /etc/logrotate.d/rsyslog
```

### Backup Strategy

Create automated backups:

```bash
#!/bin/bash
# /opt/mcs-dashboard/api/backup.sh

BACKUP_DIR="/backup/mcs-dashboard/api"
DATE=$(date +%Y%m%d_%H%M%S)
APP_DIR="/opt/mcs-dashboard/api"

mkdir -p $BACKUP_DIR/$DATE

# Stop service for consistent backup
sudo systemctl stop minecraft-dashboard

# Backup database and files
cp $APP_DIR/app.db $BACKUP_DIR/$DATE/
tar -czf $BACKUP_DIR/$DATE/servers.tar.gz -C $APP_DIR servers/
tar -czf $BACKUP_DIR/$DATE/backups.tar.gz -C $APP_DIR backups/
tar -czf $BACKUP_DIR/$DATE/templates.tar.gz -C $APP_DIR templates/
cp $APP_DIR/.env $BACKUP_DIR/$DATE/

# Restart service
sudo systemctl start minecraft-dashboard

# Cleanup old backups (keep 30 days)
find $BACKUP_DIR -type d -mtime +30 -exec rm -rf {} +

echo "Backup completed: $BACKUP_DIR/$DATE"
```

### Performance Monitoring

Monitor key metrics:

```bash
# CPU and memory usage
top -p $(pgrep -f "uvicorn app.main:app")

# Network connections
ss -tulpn | grep :8000

# Disk usage
du -sh /opt/mcs-dashboard/api/*

# API response times
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:8000/api/v1/health
```

Create `curl-format.txt`:
```
     time_namelookup:  %{time_namelookup}\n
        time_connect:  %{time_connect}\n
     time_appconnect:  %{time_appconnect}\n
    time_pretransfer:  %{time_pretransfer}\n
       time_redirect:  %{time_redirect}\n
  time_starttransfer:  %{time_starttransfer}\n
                     ----------\n
          time_total:  %{time_total}\n
```

## Troubleshooting

### Common Issues

#### Service Won't Start

```bash
# Check service status
sudo systemctl status minecraft-dashboard

# View detailed logs
sudo journalctl -u minecraft-dashboard -n 50

# Check configuration
./scripts/service-manager.sh status

# Test manual startup
cd /opt/mcs-dashboard/api
source .venv/bin/activate
uv run fastapi dev --host 0.0.0.0 --port 8000
```

#### Port Conflicts

```bash
# Check what's using port 8000
sudo netstat -tulpn | grep :8000
sudo ss -tulpn | grep :8000

# Kill conflicting process
sudo kill $(sudo lsof -ti:8000)
```

#### Permission Issues

```bash
# Fix ownership
sudo chown -R $USER:$USER /opt/mcs-dashboard/api

# Fix permissions
chmod 755 /opt/mcs-dashboard/api
chmod 600 /opt/mcs-dashboard/api/.env
chmod 600 /opt/mcs-dashboard/api/app.db
```

#### Database Issues

```bash
# Reset database (WARNING: This will delete all data)
rm /opt/mcs-dashboard/api/app.db
sudo systemctl restart minecraft-dashboard

# Check database integrity
sqlite3 /opt/mcs-dashboard/api/app.db "PRAGMA integrity_check;"
```

#### Memory Issues

```bash
# Check memory usage
free -h
ps aux | grep uvicorn

# Adjust service memory limits in systemd service file
sudo vim /etc/systemd/system/minecraft-dashboard.service
# Modify MemoryMax=2G to appropriate value
sudo systemctl daemon-reload
sudo systemctl restart minecraft-dashboard
```

### Debug Mode

Enable debug mode for detailed error information:

```bash
# Edit .env file
vim /opt/mcs-dashboard/api/.env
# Add or modify:
# LOG_LEVEL=DEBUG
# ENVIRONMENT=development

# Restart service
sudo systemctl restart minecraft-dashboard
```

### Performance Issues

```bash
# Monitor resource usage
htop
iotop
nethogs

# Check API performance
ab -n 1000 -c 10 http://localhost:8000/api/v1/health

# Profile the application
uv run python -m cProfile -o profile.stats app/main.py
```

## Development Environment

For development, use the provided development script:

```bash
# Start development server
./scripts/dev-start.sh start

# View development logs
./scripts/dev-start.sh logs-follow

# Run tests
./scripts/dev-start.sh test

# Format code
./scripts/dev-start.sh format

# Stop development server
./scripts/dev-start.sh stop
```

The development environment includes:
- Auto-reload on code changes
- Debug logging
- Test database isolation
- Development-specific configurations

## Conclusion

This comprehensive deployment guide covers all aspects of deploying the Minecraft Server Dashboard API in production. For additional support or questions, please refer to the project documentation or create an issue in the GitHub repository.

**Key Points to Remember:**
1. Always use secure, randomly generated SECRET_KEY
2. Keep the system and dependencies updated
3. Monitor logs and performance regularly
4. Implement regular backup procedures
5. Use nginx reverse proxy for production
6. Configure appropriate firewall rules
7. Monitor resource usage and scale as needed

The deployment is now complete and ready for production use!
