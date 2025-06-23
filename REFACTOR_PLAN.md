# バージョン管理リファクタリング計画

## 概要
毎回外部APIから取得する非効率な設計を、データベースベースの静的管理方式に変更する根本的なリファクタリング。

## 現状の問題分析

### 現在の実装（問題のある設計）
```python
# 毎回のリクエストで実行される処理
async def get_supported_versions():
    for server_type in ServerType:
        # 93個のMojangバージョン詳細を並列取得
        # 46個のPaperMCビルド情報を並列取得
        # 合計139個以上のHTTPリクエスト
        versions = await minecraft_version_manager.get_supported_versions(server_type)
```

**問題点：**
- 応答時間: 4-5秒
- 外部API依存: 139個以上のリクエスト
- HTTPS環境でタイムアウト発生
- 不必要なネットワーク負荷

### パフォーマンス測定結果
- 直接アクセス（HTTP）: 4.9秒
- HTTPS経由: 60秒タイムアウト（504エラー）
- 外部API: 正常（応答時間は個別に高速）

## 新設計アーキテクチャ

### 1. データベーススキーマ設計

#### MinecraftVersionsテーブル
```sql
CREATE TABLE minecraft_versions (
    id SERIAL PRIMARY KEY,
    server_type VARCHAR(20) NOT NULL,        -- 'vanilla', 'paper', 'forge'
    version VARCHAR(50) NOT NULL,            -- '1.21.6'
    download_url TEXT NOT NULL,              -- ダウンロードURL
    release_date TIMESTAMP,                  -- リリース日
    is_stable BOOLEAN DEFAULT true,          -- 安定版フラグ
    build_number INTEGER,                    -- PaperMCのビルド番号
    is_active BOOLEAN DEFAULT true,          -- 有効フラグ
    created_at TIMESTAMP DEFAULT NOW(),     -- 作成日時
    updated_at TIMESTAMP DEFAULT NOW(),     -- 更新日時

    -- インデックス
    UNIQUE(server_type, version),           -- 重複防止
    INDEX idx_server_type (server_type),
    INDEX idx_version (version),
    INDEX idx_is_active (is_active)
);
```

#### VersionUpdateLogsテーブル（管理用）
```sql
CREATE TABLE version_update_logs (
    id SERIAL PRIMARY KEY,
    update_type VARCHAR(20) NOT NULL,       -- 'manual', 'scheduled'
    server_type VARCHAR(20),                -- NULL = 全種類
    versions_added INTEGER DEFAULT 0,       -- 追加されたバージョン数
    versions_updated INTEGER DEFAULT 0,     -- 更新されたバージョン数
    versions_removed INTEGER DEFAULT 0,     -- 削除されたバージョン数
    execution_time_ms INTEGER,              -- 実行時間（ミリ秒）
    status VARCHAR(20) NOT NULL,            -- 'success', 'failed', 'partial'
    error_message TEXT,                     -- エラーメッセージ
    executed_by_user_id INTEGER,            -- 実行ユーザー（手動更新時）
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,

    INDEX idx_update_type (update_type),
    INDEX idx_status (status),
    INDEX idx_started_at (started_at)
);
```

### 2. 新しいサービス構造

#### VersionRepository（データアクセス層）
```python
class VersionRepository:
    """バージョン情報のデータベース操作"""

    async def get_all_versions(self) -> List[MinecraftVersion]:
        """全てのアクティブなバージョンを取得"""

    async def get_versions_by_type(self, server_type: ServerType) -> List[MinecraftVersion]:
        """指定されたサーバータイプのバージョンを取得"""

    async def upsert_version(self, version_info: VersionInfo) -> MinecraftVersion:
        """バージョン情報を挿入または更新"""

    async def deactivate_old_versions(self, server_type: ServerType, keep_versions: List[str]):
        """古いバージョンを非アクティブ化"""
```

#### VersionUpdateService（更新ロジック）
```python
class VersionUpdateService:
    """バージョン情報の更新処理"""

    async def refresh_all_versions(self) -> VersionUpdateResult:
        """全てのサーバータイプのバージョンを更新"""

    async def refresh_server_type(self, server_type: ServerType) -> VersionUpdateResult:
        """指定されたサーバータイプのバージョンを更新"""

    async def get_update_status(self) -> UpdateStatus:
        """最後の更新状況を取得"""
```

#### VersionScheduler（スケジュール管理）
```python
class VersionScheduler:
    """バージョン更新のスケジュール管理"""

    async def start_scheduler(self):
        """定期更新タスクを開始"""

    async def schedule_update(self, delay_hours: int = 0):
        """手動での更新スケジュール"""
```

### 3. 修正されるエンドポイント

#### 高速化されるエンドポイント
```python
@router.get("/versions/supported")
async def get_supported_versions():
    """DBから即座にバージョン情報を返す（10-50ms）"""
    versions = await version_repository.get_all_versions()
    return SupportedVersionsResponse(versions=versions)

@router.post("/versions/refresh")  # 新規追加
async def refresh_versions(current_user: User = Depends(get_admin_user)):
    """手動でバージョン情報を更新（管理者専用）"""
    result = await version_update_service.refresh_all_versions()
    return VersionUpdateResponse(result=result)

@router.get("/versions/update-status")  # 新規追加
async def get_update_status():
    """最後の更新状況を取得"""
    status = await version_update_service.get_update_status()
    return UpdateStatusResponse(status=status)
```

## 実装フェーズ

### Phase 1: データベース基盤構築
**所要時間: 1-2日**

1. **モデル作成**
   - `app/versions/models.py` - MinecraftVersion, VersionUpdateLog
   - SQLAlchemyモデル定義

2. **リポジトリ作成**
   - `app/versions/repository.py` - VersionRepository
   - 基本的なCRUD操作

3. **マイグレーション**
   - データベースマイグレーション実行
   - テストデータ投入

### Phase 2: 更新サービス実装
**所要時間: 2-3日**

1. **VersionUpdateService実装**
   - `app/versions/services.py`
   - 既存のversion_manager.pyのロジックを活用

2. **バックグラウンドタスク統合**
   - `app/versions/scheduler.py`
   - 既存のlifespanシステムに統合

3. **初回データ移行**
   - 現在のAPIから初回データを取得してDB投入

### Phase 3: エンドポイント切り替え
**所要時間: 1日**

1. **新エンドポイント実装**
   - `app/versions/router.py`
   - 管理用エンドポイント追加

2. **既存エンドポイント修正**
   - `app/servers/routers/utilities.py`
   - DBからの取得に変更

3. **テスト調整**
   - 既存テストの修正
   - 新機能のテスト追加

### Phase 4: 監視・運用機能
**所要時間: 1-2日**

1. **管理UI対応**
   - 手動更新ボタン
   - 更新履歴表示

2. **監視機能**
   - 更新失敗アラート
   - パフォーマンスメトリクス

3. **ドキュメント更新**

## 期待される効果

### パフォーマンス改善
- **応答時間**: 4-5秒 → 10-50ms（100倍高速化）
- **外部API依存**: 通常時は0リクエスト
- **同時接続処理**: 大幅改善

### 可用性向上
- 外部API障害時も継続動作
- HTTPS環境での504エラー解消
- より安定したサービス提供

### 運用性向上
- バージョン更新の可視化
- 手動更新機能
- 更新履歴の追跡
- エラー監視

## リスク管理

### 移行時のリスク
1. **データ不整合**: 段階的移行で最小化
2. **ダウンタイム**: ゼロダウンタイム移行
3. **ロールバック**: 既存コードは保持

### 運用時のリスク
1. **外部API変更**: フォールバック機能
2. **データ古化**: 定期更新 + 手動更新
3. **ディスク容量**: 定期クリーンアップ

## 破棄する一時的修正

以下の修正は本リファクタリング完了後に不要となる：

1. **Issue #89のタイムアウト設定**（PR #90）
   - `version_manager.py`のタイムアウト設定
   - 外部API呼び出しの最適化

2. **Issue #91のnginx設定修正**
   - プロキシタイムアウト設定
   - 長時間処理対応

**理由**: 根本的に処理時間が10-50msになるため、タイムアウト対策が不要になる。

## 次のステップ

1. **Phase 1から順次実装開始**
2. **各フェーズ完了後にテスト実行**
3. **段階的なデプロイで安全性確保**
4. **完了後、一時的修正の削除**
