# Nginx Reverse Proxy 500 Error Fix

## Problem

When running the MC Server Dashboard API behind an Nginx reverse proxy with HTTPS, the `POST /servers` endpoint returns a 500 error.

## Root Cause

The issue is caused by timeout problems. The server creation process involves:
- Downloading large Minecraft server JAR files (100+ MB)
- Making multiple external API calls to Mojang/PaperMC servers
- Creating server directories and configuration files

This process can take longer than Nginx's default proxy timeout of 60 seconds, causing Nginx to terminate the connection and return a gateway timeout error.

## Solution

### 1. Nginx Configuration Update

Add a specific location block for the server creation endpoint with extended timeouts:

```nginx
# Server creation endpoints with extended timeouts
location ~ ^/api/v1/servers$ {
    proxy_pass http://minecraft_dashboard_backend;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Port $server_port;

    # Extended timeouts for server creation (JAR downloads, etc.)
    proxy_connect_timeout 300s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;

    # Rate limiting for API endpoints
    limit_req zone=api burst=20 nodelay;
}
```

### 2. FastAPI Configuration Update

Add TrustedHostMiddleware to properly handle proxy headers:

```python
from fastapi.middleware.trustedhost import TrustedHostMiddleware

# Add TrustedHostMiddleware to handle proxy headers correctly
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],  # Configure with actual domains in production
)
```

### 3. FastAPI Proxy Headers Configuration

Configure FastAPI to trust proxy headers:

```python
app = FastAPI(
    lifespan=lifespan,
    # Configure app to trust proxy headers when behind reverse proxy
    root_path=settings.api_prefix if hasattr(settings, 'api_prefix') else "",
    root_path_in_servers=True,
)
```

## Applying the Changes

1. Update the Nginx configuration file at `/etc/nginx/sites-available/minecraft-dashboard.conf`
2. Test the configuration: `sudo nginx -t`
3. Reload Nginx: `sudo systemctl reload nginx`
4. Restart the FastAPI application to apply the code changes

## Additional Considerations

### Long-term Solutions

1. **Background Tasks**: Consider implementing the JAR download process as a background task to avoid long request times
2. **Progress Tracking**: Implement WebSocket-based progress updates for server creation
3. **Caching**: Improve JAR file caching to avoid repeated downloads
4. **Circuit Breakers**: Add circuit breakers for external API calls to handle failures gracefully

### Monitoring

Monitor the following metrics:
- Request duration for POST /servers
- Nginx error logs for timeout errors
- Application logs for JAR download times
- External API response times

## Related Issues

This fix is similar to the timeout issue resolved in commit `a3ef0bb` for the version endpoint, which added timeout configuration to prevent 504 errors.
