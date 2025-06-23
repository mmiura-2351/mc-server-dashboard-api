# Nginx Configuration for Minecraft Dashboard API

This directory contains nginx configuration files for the Minecraft Dashboard API.

## Files

- `minecraft-dashboard.conf` - Main nginx configuration file
- `README.md` - This documentation file

## Installation

### 1. Install Nginx

```bash
sudo apt update
sudo apt install -y nginx
```

### 2. Deploy Configuration

```bash
# Copy configuration file
sudo cp /opt/mcs-dashboard/api/deployment/nginx/minecraft-dashboard.conf /etc/nginx/sites-available/

# Enable the site
sudo ln -s /etc/nginx/sites-available/minecraft-dashboard.conf /etc/nginx/sites-enabled/

# Remove default site (optional)
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
sudo systemctl enable nginx
```

### 3. SSL Certificate Setup

#### Option A: Let's Encrypt (Recommended)

```bash
# Install certbot
sudo apt install -y certbot python3-certbot-nginx

# Obtain certificate (replace your-domain.com)
sudo certbot --nginx -d your-domain.com

# Auto-renewal
sudo systemctl enable certbot.timer
```

#### Option B: Self-Signed Certificate (Development/Testing)

```bash
# Create certificate directory
sudo mkdir -p /etc/ssl/private

# Generate self-signed certificate
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/ssl/private/minecraft-dashboard.key \
    -out /etc/ssl/certs/minecraft-dashboard.crt \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

# Set proper permissions
sudo chmod 600 /etc/ssl/private/minecraft-dashboard.key
sudo chmod 644 /etc/ssl/certs/minecraft-dashboard.crt
```

### 4. Update Configuration

Edit `/etc/nginx/sites-available/minecraft-dashboard.conf` and update:

- `server_name` - Replace with your actual domain name
- SSL certificate paths (if using custom certificates)
- Rate limiting settings as needed
- File upload size limits

### 5. Firewall Configuration

```bash
# Allow nginx through firewall
sudo ufw allow 'Nginx Full'

# Or manually allow ports
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

## Configuration Features

### Security Features

- **HTTPS enforcement** with modern TLS configuration
- **Security headers** including HSTS, CSP, and XSS protection
- **Rate limiting** for different endpoint types
- **Access restrictions** for sensitive files and directories
- **Blocking of common exploit attempts**

### Performance Features

- **HTTP/2 support** for improved performance
- **SSL session caching** for reduced handshake overhead
- **Proxy buffering** for better throughput
- **Static file caching** with appropriate headers
- **WebSocket support** for real-time features

### Rate Limiting

The configuration includes different rate limiting zones:

- **API endpoints**: 10 requests/second with burst of 20
- **Authentication**: 5 requests/second with burst of 10
- **File uploads**: 2 requests/second with burst of 5

### File Upload Limits

- Default upload limit: 100MB
- Can be adjusted per location block
- Includes extended timeouts for large uploads

## Monitoring

### Nginx Status

Access nginx status page (internal only):

```bash
curl http://127.0.0.1:8080/nginx_status
```

### Log Files

- Access logs: `/var/log/nginx/minecraft-dashboard.access.log`
- Error logs: `/var/log/nginx/minecraft-dashboard.error.log`

### Log Rotation

Nginx logs are automatically rotated by logrotate. To manually rotate:

```bash
sudo logrotate -f /etc/logrotate.d/nginx
```

## Troubleshooting

### Common Issues

#### Configuration Test Fails

```bash
# Test configuration syntax
sudo nginx -t

# Check for conflicts
sudo nginx -T
```

#### SSL Certificate Issues

```bash
# Test SSL configuration
openssl s_client -connect your-domain.com:443 -servername your-domain.com

# Check certificate expiration
openssl x509 -in /etc/ssl/certs/minecraft-dashboard.crt -noout -dates
```

#### Rate Limiting Issues

```bash
# Check rate limit status in logs
sudo tail -f /var/log/nginx/minecraft-dashboard.error.log | grep "limiting requests"

# Adjust rate limits in configuration file
sudo vim /etc/nginx/sites-available/minecraft-dashboard.conf
```

#### WebSocket Connection Issues

Ensure the following headers are properly set:
- `Upgrade: websocket`
- `Connection: upgrade`
- `Sec-WebSocket-*` headers

### Performance Tuning

#### Worker Processes

Edit `/etc/nginx/nginx.conf`:

```nginx
# Set to number of CPU cores
worker_processes auto;

# Increase worker connections
events {
    worker_connections 1024;
    use epoll;
}
```

#### Buffer Sizes

For high-traffic sites, consider increasing buffer sizes:

```nginx
proxy_buffer_size 128k;
proxy_buffers 8 256k;
proxy_busy_buffers_size 256k;
```

#### File Descriptor Limits

```bash
# Increase system limits
echo "nginx soft nofile 65536" | sudo tee -a /etc/security/limits.conf
echo "nginx hard nofile 65536" | sudo tee -a /etc/security/limits.conf
```

## Security Considerations

### Regular Updates

```bash
# Update nginx regularly
sudo apt update && sudo apt upgrade nginx

# Monitor security advisories
```

### Access Control

Consider implementing additional access controls:

- IP whitelisting for admin endpoints
- Geographic blocking
- Client certificate authentication

### Monitoring

Set up monitoring for:

- Failed authentication attempts
- Rate limit violations
- Unusual traffic patterns
- SSL certificate expiration

## Integration with API

The nginx configuration is designed to work seamlessly with the Minecraft Dashboard API:

- Health checks are properly routed
- WebSocket connections for real-time features
- File upload handling with appropriate limits
- API documentation serving
- Rate limiting to protect the backend

For any issues or questions, refer to the main deployment documentation or create an issue in the project repository.
