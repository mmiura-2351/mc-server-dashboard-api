# Minecraft Server Dashboard API - Deployment Guide

本ガイドでは、Minecraft Server Dashboard APIをLinux環境に最小限の設定でデプロイする方法について説明します。

## 目次

1. [前提条件](#前提条件)
2. [アプリケーションのセットアップ](#アプリケーションのセットアップ)
3. [systemd サービス設定](#systemd-サービス設定)
4. [監視とログ管理](#監視とログ管理)
5. [バックアップ戦略](#バックアップ戦略)
6. [トラブルシューティング](#トラブルシューティング)

## 前提条件

### 必要なソフトウェア
- **Python 3.13+** (uv package manager で自動インストール)
- **Java** (複数バージョンのMinecraft サーバーサポートのため)
  - Java 8, 17, 21 (Minecraft バージョンに応じて)

### ネットワーク要件
- API アプリケーション用ポート (デフォルト: 8000)
- Minecraft サーバー用ポート範囲 (25565-25600 推奨)

## アプリケーションのセットアップ

### 1. 必要なパッケージのインストール

```bash
sudo apt update
sudo apt install -y git curl
```

### 2. Java のインストール

```bash
# 複数のJavaバージョンをインストール（Minecraftバージョン対応）
sudo apt install -y openjdk-8-jdk openjdk-17-jdk openjdk-21-jdk

# インストール確認
java -version
update-alternatives --list java
```

### 3. uv パッケージマネージャーのインストール

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

### 4. アプリケーションのデプロイ

```bash
# アプリケーションディレクトリの作成
sudo mkdir -p /opt/mcs-dashboard
sudo chown $USER:$USER /opt/mcs-dashboard

# ディレクトリに移動
cd /opt/mcs-dashboard

# リポジトリのクローン
git clone https://github.com/mmiura-2351/mc-server-dashboard-api.git .

# 依存関係のインストール
uv sync

# 環境変数の設定
cp .env.example .env

# 安全なSECRET_KEYを生成
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"

# .envファイルを編集（生成されたSECRET_KEYを使用）
vim .env
```

### 5. 環境変数の設定例

```bash
# .env ファイル
SECRET_KEY=生成された安全なキー（デフォルト値は使用しないこと）
DATABASE_URL=sqlite:///./app.db
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ENVIRONMENT=production

# Java パス設定（必要な場合）
JAVA_8_PATH=/usr/lib/jvm/java-8-openjdk-amd64/bin/java
JAVA_17_PATH=/usr/lib/jvm/java-17-openjdk-amd64/bin/java
JAVA_21_PATH=/usr/lib/jvm/java-21-openjdk-amd64/bin/java
```

**重要**: `SECRET_KEY`は必ず上記のコマンドで生成した安全なキーを使用してください。デフォルト値のままではアプリケーションが起動しません。

## systemd サービス設定

### サービスファイルの設置

```bash
# 提供されているサービスファイルをコピーし、現在のユーザーに設定
sudo cp /opt/mcs-dashboard/minecraft-dashboard.service /etc/systemd/system/
sudo sed -i "7a User=$USER\nGroup=$USER" /etc/systemd/system/minecraft-dashboard.service

# または手動で作成
sudo vim /etc/systemd/system/minecraft-dashboard.service
```

サービスファイルの内容（`minecraft-dashboard.service`）:
```ini
[Unit]
Description=Minecraft Dashboard API
After=network.target

[Service]
Type=simple
User=your-username  # 実際のユーザー名に置き換え
Group=your-username  # 実際のユーザー名に置き換え
WorkingDirectory=/opt/mcs-dashboard
Environment=PATH=/opt/mcs-dashboard/.venv/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=-/opt/mcs-dashboard/.env
ExecStart=/opt/mcs-dashboard/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
ExecStop=/bin/kill -TERM $MAINPID
ExecReload=/bin/kill -HUP $MAINPID
KillMode=mixed
KillSignal=SIGTERM
TimeoutStopSec=30
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### サービスの有効化と開始

```bash
# サービスの有効化と開始
sudo systemctl daemon-reload
sudo systemctl enable minecraft-dashboard
sudo systemctl start minecraft-dashboard

# ステータス確認
sudo systemctl status minecraft-dashboard

# エラーが発生した場合のログ確認
sudo journalctl -u minecraft-dashboard -n 50 --no-pager

# 手動での動作確認
cd /opt/mcs-dashboard
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

# よくあるエラー: SECRET_KEY validation error
# 解決方法: .envファイルのSECRET_KEYを安全な値に変更
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"

# サービスの制御コマンド
sudo systemctl stop minecraft-dashboard     # サービス停止
sudo systemctl restart minecraft-dashboard  # サービス再起動
sudo systemctl reload minecraft-dashboard   # 設定リロード
```

## 監視とログ管理

### ログの確認

```bash
# systemd ログの確認
sudo journalctl -u minecraft-dashboard -f

# アプリケーションログの確認（もしあれば）
tail -f /opt/mcs-dashboard/logs/app.log
```

### ヘルスチェック

```bash
# ヘルスチェックエンドポイント
curl http://localhost:8000/health

# メトリクスエンドポイント
curl http://localhost:8000/metrics
```

## バックアップ戦略

### アプリケーションデータバックアップ

```bash
#!/bin/bash
# backup.sh

BACKUP_DIR="/backup/mcs-dashboard"
DATE=$(date +%Y%m%d_%H%M%S)
APP_DIR="/opt/mcs-dashboard"

mkdir -p $BACKUP_DIR/$DATE

# データベースバックアップ（SQLiteの場合）
cp $APP_DIR/app.db $BACKUP_DIR/$DATE/

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

## トラブルシューティング

### 一般的な問題と解決方法

#### 1. アプリケーション起動の問題

```bash
# ログの確認
sudo journalctl -u minecraft-dashboard -f

# 手動での起動テスト
cd /opt/mcs-dashboard
source .venv/bin/activate
uv run fastapi dev  # 開発モードでテスト
```

#### 2. Java の問題

```bash
# インストールされているJavaバージョンの確認
update-alternatives --list java

# Java パスの設定確認
echo $JAVA_8_PATH
echo $JAVA_17_PATH
echo $JAVA_21_PATH

# Java バージョンの手動テスト
/usr/lib/jvm/java-8-openjdk-amd64/bin/java -version
/usr/lib/jvm/java-17-openjdk-amd64/bin/java -version
/usr/lib/jvm/java-21-openjdk-amd64/bin/java -version
```

#### 3. ポート競合の問題

```bash
# ポート使用状況の確認
sudo netstat -tlnp | grep :8000
sudo ss -tlnp | grep :8000

# プロセスの確認
sudo lsof -i :8000
```

#### 4. ディスク容量の問題

```bash
# ディスク使用量の確認
df -h
du -sh /opt/mcs-dashboard/*

# 大きなファイルの検索
find /opt/mcs-dashboard -type f -size +100M -exec ls -lh {} \;
```

## まとめ

このデプロイメントガイドでは、Minecraft Server Dashboard API を Linux 環境に最小限の設定でデプロイする手順を説明しました。基本的なデプロイメントでは、以下の点を確認してください：

1. **依存関係**: Python 3.13+ と必要な Java バージョンのインストール
2. **アプリケーション設定**: 適切な環境変数の設定
3. **サービス管理**: systemd を使用したサービスの自動起動設定
4. **監視**: ログ確認とヘルスチェックエンドポイントの活用
5. **バックアップ**: 定期的なデータバックアップの実施

必要に応じて、リバースプロキシやSSL/TLS設定、セキュリティ強化などの追加設定を行ってください。
