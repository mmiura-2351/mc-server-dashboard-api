# Minecraft Server Dashboard API - Deployment Guide

本ガイドでは、Minecraft Server Dashboard APIをLinux環境にデプロイする方法について説明します。

## 目次

1. [前提条件](#前提条件)
2. [環境設定](#環境設定)
3. [サーバーデプロイ](#サーバーデプロイ)
4. [リバースプロキシ設定](#リバースプロキシ設定)
5. [SSL/TLS 設定](#ssltls-設定)
6. [監視とログ管理](#監視とログ管理)
7. [バックアップ戦略](#バックアップ戦略)
8. [セキュリティ考慮事項](#セキュリティ考慮事項)
9. [トラブルシューティング](#トラブルシューティング)

## 前提条件

### 必要なソフトウェア
- **Python 3.13+** (uv package manager 推奨)
- **Java** (複数バージョンのMinecraft サーバーサポートのため)
  - Java 8, 16, 17, 21 (Minecraft バージョンに応じて)
- **SQLite** (デフォルト) または **PostgreSQL** (本番環境推奨)
- **Nginx** または **Apache** (リバースプロキシとして)

### ネットワーク要件
- HTTP/HTTPS トラフィック用ポート (80/443)
- API アプリケーション用ポート (デフォルト: 8000)
- Minecraft サーバー用ポート範囲 (25565-25600 推奨)
- WebSocket 接続のサポート

## 環境設定

### 1. ユーザーアカウントの作成

```bash
# 専用ユーザーの作成
sudo adduser minecraft-dashboard
sudo usermod -aG sudo minecraft-dashboard

# ユーザーの切り替え
sudo su - minecraft-dashboard
```

### 2. 必要なパッケージのインストール

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install -y python3.13 python3.13-venv git nginx postgresql postgresql-contrib
```

#### CentOS/RHEL
```bash
sudo yum update
sudo yum install -y python3.13 python3.13-venv git nginx postgresql postgresql-server
```

### 3. Java のインストール

```bash
# 複数のJavaバージョンをインストール
sudo apt install -y openjdk-8-jdk openjdk-17-jdk openjdk-21-jdk

# インストール確認
java -version
update-alternatives --list java
```

### 4. uv パッケージマネージャーのインストール

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

## サーバーデプロイ

### 1. アプリケーションのセットアップ

```bash
# アプリケーションディレクトリの作成
sudo mkdir -p /opt/minecraft-dashboard
sudo chown minecraft-dashboard:minecraft-dashboard /opt/minecraft-dashboard
cd /opt/minecraft-dashboard

# リポジトリのクローン
git clone https://github.com/your-repo/mc-server-dashboard-api.git .

# 仮想環境のセットアップ
uv sync

# 環境変数の設定
cp .env.example .env
nano .env  # 本番環境用に編集
```

### 2. PostgreSQL データベースのセットアップ

```bash
# PostgreSQL の設定
sudo systemctl start postgresql
sudo systemctl enable postgresql

# データベースとユーザーの作成
sudo -u postgres psql
```

```sql
CREATE DATABASE minecraft_dashboard;
CREATE USER minecraft WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE minecraft_dashboard TO minecraft;
\q
```

### 3. systemd サービスの作成

```bash
# サービスファイルの作成
sudo nano /etc/systemd/system/minecraft-dashboard.service
```

```ini
[Unit]
Description=Minecraft Dashboard API
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=minecraft-dashboard
Group=minecraft-dashboard
WorkingDirectory=/opt/minecraft-dashboard
Environment=PATH=/opt/minecraft-dashboard/.venv/bin
EnvironmentFile=/opt/minecraft-dashboard/.env
ExecStart=/opt/minecraft-dashboard/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

# セキュリティ設定
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/minecraft-dashboard
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

```bash
# サービスの有効化と開始
sudo systemctl daemon-reload
sudo systemctl enable minecraft-dashboard
sudo systemctl start minecraft-dashboard

# ステータス確認
sudo systemctl status minecraft-dashboard
```

## リバースプロキシ設定

### Nginx 設定

```bash
# Nginx 設定ファイルの作成
sudo nano /etc/nginx/sites-available/minecraft-dashboard
```

```nginx
upstream minecraft_dashboard {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;

    # HTTPS へのリダイレクト
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    # SSL 証明書
    ssl_certificate /etc/ssl/certs/minecraft-dashboard.crt;
    ssl_certificate_key /etc/ssl/private/minecraft-dashboard.key;

    # SSL 設定
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # セキュリティヘッダー
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload";

    # 最大アップロードサイズ
    client_max_body_size 100M;

    location / {
        proxy_pass http://minecraft_dashboard;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket サポート
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # タイムアウト設定
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # 静的ファイルの配信（必要に応じて）
    location /static/ {
        alias /opt/minecraft-dashboard/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # ヘルスチェックエンドポイント
    location /health {
        proxy_pass http://minecraft_dashboard;
        access_log off;
    }
}
```

```bash
# 設定の有効化
sudo ln -s /etc/nginx/sites-available/minecraft-dashboard /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## SSL/TLS 設定

### Let's Encrypt を使用した無料SSL証明書

```bash
# Certbot のインストール
sudo apt install certbot python3-certbot-nginx

# SSL 証明書の取得
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# 自動更新の設定
sudo crontab -e
# 以下を追加
0 12 * * * /usr/bin/certbot renew --quiet
```

## 監視とログ管理

### 1. ログローテーション設定

```bash
# logrotate 設定の作成
sudo nano /etc/logrotate.d/minecraft-dashboard
```

```
/opt/minecraft-dashboard/logs/*.log {
    daily
    missingok
    rotate 52
    compress
    delaycompress
    notifempty
    copytruncate
    postrotate
        systemctl reload minecraft-dashboard
    endscript
}
```

### 2. Prometheus メトリクス設定

FastAPI アプリケーションでは `/metrics` エンドポイントが利用可能です。

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'minecraft-dashboard'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 30s
```

### 3. ヘルスチェック監視

```bash
# ヘルスチェックスクリプト
#!/bin/bash
# /opt/minecraft-dashboard/scripts/health_check.sh

HEALTH_URL="http://localhost:8000/health"
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" $HEALTH_URL)

if [ $RESPONSE -eq 200 ]; then
    echo "$(date): Service is healthy"
    exit 0
else
    echo "$(date): Service is unhealthy - HTTP $RESPONSE"
    exit 1
fi
```

```bash
# cron での定期ヘルスチェック
*/5 * * * * /opt/minecraft-dashboard/scripts/health_check.sh >> /var/log/minecraft-dashboard-health.log 2>&1
```

## バックアップ戦略

### 1. アプリケーションデータバックアップ

```bash
#!/bin/bash
# /opt/minecraft-dashboard/scripts/backup.sh

BACKUP_DIR="/backup/minecraft-dashboard"
DATE=$(date +%Y%m%d_%H%M%S)
APP_DIR="/opt/minecraft-dashboard"

mkdir -p $BACKUP_DIR/$DATE

# データベースバックアップ
pg_dump -h localhost -U minecraft minecraft_dashboard > $BACKUP_DIR/$DATE/database.sql

# サーバーファイルのバックアップ
tar -czf $BACKUP_DIR/$DATE/servers.tar.gz -C $APP_DIR servers/
tar -czf $BACKUP_DIR/$DATE/backups.tar.gz -C $APP_DIR backups/
tar -czf $BACKUP_DIR/$DATE/templates.tar.gz -C $APP_DIR templates/

# 設定ファイルのバックアップ
cp $APP_DIR/.env $BACKUP_DIR/$DATE/
cp -r $APP_DIR/file_history $BACKUP_DIR/$DATE/

# 古いバックアップの削除（30日以上古いもの）
find $BACKUP_DIR -type d -mtime +30 -exec rm -rf {} +

echo "Backup completed: $BACKUP_DIR/$DATE"
```

### 2. 自動バックアップスケジュール

```bash
# crontab に追加
0 2 * * * /opt/minecraft-dashboard/scripts/backup.sh >> /var/log/minecraft-dashboard-backup.log 2>&1
```

## セキュリティ考慮事項

### 1. ファイアウォール設定

```bash
# UFW を使用した基本的なファイアウォール設定
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 25565:25600/tcp  # Minecraft サーバーポート範囲
sudo ufw enable
```

### 2. fail2ban 設定

```bash
# fail2ban のインストール
sudo apt install fail2ban

# 設定ファイルの作成
sudo nano /etc/fail2ban/jail.local
```

```ini
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[nginx-http-auth]
enabled = true
filter = nginx-http-auth
logpath = /var/log/nginx/error.log

[nginx-noscript]
enabled = true
filter = nginx-noscript
logpath = /var/log/nginx/access.log
maxretry = 6
```

### 3. セキュリティアップデート

```bash
# 自動セキュリティアップデートの設定
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

## トラブルシューティング

### 一般的な問題と解決方法

#### 1. アプリケーション起動の問題

```bash
# ログの確認
sudo journalctl -u minecraft-dashboard -f

# 手動での起動テスト
cd /opt/minecraft-dashboard
source .venv/bin/activate
uv run fastapi dev  # 開発モードでテスト
```

#### 2. データベース接続の問題

```bash
# PostgreSQL の状態確認
sudo systemctl status postgresql

# 接続テスト
psql -h localhost -U minecraft -d minecraft_dashboard

# データベースログの確認
sudo tail -f /var/log/postgresql/postgresql-*.log
```

#### 3. Java の問題

```bash
# インストールされているJavaバージョンの確認
update-alternatives --list java

# Java パスの設定確認
echo $JAVA_17_PATH
echo $JAVA_21_PATH

# Java バージョンの手動テスト
/usr/lib/jvm/java-17-openjdk-amd64/bin/java -version
```

#### 4. ポート競合の問題

```bash
# ポート使用状況の確認
sudo netstat -tlnp | grep :8000
sudo ss -tlnp | grep :8000

# プロセスの確認
sudo lsof -i :8000
```

#### 5. ディスク容量の問題

```bash
# ディスク使用量の確認
df -h
du -sh /opt/minecraft-dashboard/*

# 大きなファイルの検索
find /opt/minecraft-dashboard -type f -size +100M -exec ls -lh {} \;
```

### パフォーマンス最適化

#### 1. データベース最適化

```sql
-- PostgreSQL の設定最適化
-- /var/lib/postgresql/data/postgresql.conf

shared_buffers = 256MB
effective_cache_size = 1GB
work_mem = 4MB
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
```

#### 2. アプリケーション最適化

```bash
# Uvicorn ワーカープロセス数の調整
# systemd サービスファイルで
ExecStart=/opt/minecraft-dashboard/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### ログ分析

```bash
# エラーログの確認
sudo journalctl -u minecraft-dashboard | grep ERROR

# アクセスパターンの分析
sudo tail -f /var/log/nginx/access.log | grep -v "GET /health"

# パフォーマンスメトリクスの確認
curl http://localhost:8000/metrics
```

## まとめ

このデプロイメントガイドでは、Minecraft Server Dashboard API を本番環境で安全かつ効率的に運用するための包括的な手順を説明しました。本番環境では、以下の点を特に重視してください：

1. **セキュリティ**: SSL/TLS、ファイアウォール、定期的な更新
2. **監視**: ヘルスチェック、ログ管理、メトリクス収集
3. **バックアップ**: 定期的なデータバックアップと復旧手順の確認
4. **パフォーマンス**: リソース使用量の監視と最適化

定期的な保守とアップデートを行い、システムの安定性と安全性を維持してください。
