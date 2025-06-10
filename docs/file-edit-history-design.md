# ファイル編集履歴管理システム設計書

## 📋 **概要**

ファイル編集時のバックアップ機能を、`servers/`ディレクトリから独立した専用の履歴管理システムに改善する設計書です。

## 🎯 **目的・課題**

### 現在の問題点
- バックアップファイルが`servers/`内に混在
- ファイル管理UIで表示され操作の邪魔
- 履歴管理が困難
- 自動クリーンアップなし

### 改善目標
- 専用ディレクトリでの履歴管理
- サーバー構造のミラー化
- 編集履歴の呼び戻し機能
- 直感的な履歴管理

## 🏗️ **アーキテクチャ設計**

### 1. ディレクトリ構造設計

```
mc-server-dashboard-api/
├── servers/                    # 現行サーバーディレクトリ
│   ├── server_1/
│   │   ├── server.properties
│   │   ├── eula.txt
│   │   └── world/
│   └── server_2/
└── file_history/               # 新設：編集履歴専用
    ├── server_1/               # サーバーIDごと
    │   ├── server.properties/  # ファイルごとの履歴ディレクトリ
    │   │   ├── v001_20250607_154523.properties
    │   │   ├── v002_20250607_163012.properties
    │   │   └── latest.properties
    │   ├── eula.txt/
    │   │   ├── v001_20250607_155000.txt
    │   │   └── latest.txt
    │   └── plugins/
    │       └── config.yml/
    │           ├── v001_20250607_160000.yml
    │           └── latest.yml
    └── server_2/
```

### 2. データベース設計

#### 新テーブル: `file_edit_history`
```sql
CREATE TABLE file_edit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    file_path VARCHAR(500) NOT NULL,        -- 元ファイルの相対パス (e.g., "server.properties", "plugins/config.yml")
    version_number INTEGER NOT NULL,        -- バージョン番号 (1, 2, 3, ...)
    backup_file_path VARCHAR(500) NOT NULL, -- バックアップファイルの絶対パス
    file_size BIGINT NOT NULL,
    content_hash VARCHAR(64),               -- ファイル内容のSHA256ハッシュ（重複検出用）
    editor_user_id INTEGER,                 -- 編集者のユーザーID
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    description TEXT,                       -- 編集内容の説明（オプション）
    
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE,
    FOREIGN KEY (editor_user_id) REFERENCES users(id) ON DELETE SET NULL,
    
    UNIQUE(server_id, file_path, version_number)
);

CREATE INDEX idx_file_history_server_file ON file_edit_history(server_id, file_path);
CREATE INDEX idx_file_history_created ON file_edit_history(created_at);
```

## 🔧 **サービス設計**

### 3. FileHistoryService クラス

```python
class FileHistoryService:
    """ファイル編集履歴管理サービス"""
    
    def __init__(self):
        self.history_base_dir = Path("./file_history")
        self.max_versions_per_file = 50  # ファイルごとの最大履歴数
        self.auto_cleanup_days = 30      # 自動削除までの日数
    
    async def create_version_backup(
        self, 
        server_id: int, 
        file_path: str, 
        content: str,
        user_id: int,
        description: str = None
    ) -> FileHistoryRecord:
        """ファイル編集前のバックアップ作成"""
        
    async def get_file_history(
        self, 
        server_id: int, 
        file_path: str,
        limit: int = 20
    ) -> List[FileHistoryRecord]:
        """ファイルの編集履歴取得"""
        
    async def restore_from_history(
        self, 
        server_id: int, 
        file_path: str, 
        version_number: int,
        user_id: int
    ) -> RestoreResult:
        """指定バージョンからの復元"""
        
    async def get_version_content(
        self, 
        server_id: int, 
        file_path: str, 
        version_number: int
    ) -> str:
        """特定バージョンの内容取得"""
        
    async def delete_version(
        self, 
        server_id: int, 
        file_path: str, 
        version_number: int
    ) -> bool:
        """特定バージョンの削除"""
        
    async def cleanup_old_versions(self, server_id: int = None) -> CleanupResult:
        """古いバージョンの自動クリーンアップ"""
```

### 4. バックアップ作成プロセス

```python
async def create_version_backup(self, server_id: int, file_path: str, content: str, user_id: int, description: str = None):
    """
    1. ファイルパス正規化とディレクトリ作成
    2. 次のバージョン番号計算
    3. コンテンツハッシュ計算（重複チェック用）
    4. バックアップファイル作成
    5. データベース記録
    6. 古いバージョンの自動クリーンアップ
    """
    
    # ディレクトリ構造作成
    history_dir = self.history_base_dir / str(server_id) / file_path
    history_dir.mkdir(parents=True, exist_ok=True)
    
    # バージョン番号決定
    version_num = await self._get_next_version_number(server_id, file_path)
    
    # ファイル名生成
    file_extension = Path(file_path).suffix
    backup_filename = f"v{version_num:03d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{file_extension}"
    backup_file_path = history_dir / backup_filename
    
    # コンテンツハッシュ
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    
    # 重複チェック
    if await self._is_duplicate_content(server_id, file_path, content_hash):
        return None  # 同じ内容の場合はバックアップ作成しない
    
    # ファイル作成
    async with aiofiles.open(backup_file_path, 'w', encoding='utf-8') as f:
        await f.write(content)
    
    # データベース記録
    record = FileHistoryRecord(
        server_id=server_id,
        file_path=file_path,
        version_number=version_num,
        backup_file_path=str(backup_file_path),
        file_size=len(content.encode()),
        content_hash=content_hash,
        editor_user_id=user_id,
        description=description
    )
    
    # 自動クリーンアップ
    await self._cleanup_excess_versions(server_id, file_path)
    
    return record
```

## 📊 **API設計**

### 5. 新しいAPIエンドポイント

```python
# ファイル編集履歴取得
@router.get("/servers/{server_id}/files/{file_path:path}/history")
async def get_file_edit_history(
    server_id: int,
    file_path: str,
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> FileHistoryListResponse:
    """ファイルの編集履歴を取得"""

# 特定バージョンの内容取得
@router.get("/servers/{server_id}/files/{file_path:path}/history/{version}")
async def get_file_version_content(
    server_id: int,
    file_path: str,
    version: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> FileVersionContentResponse:
    """特定バージョンの内容を取得"""

# バージョンからの復元
@router.post("/servers/{server_id}/files/{file_path:path}/history/{version}/restore")
async def restore_from_version(
    server_id: int,
    file_path: str,
    version: int,
    request: RestoreFromVersionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> RestoreResponse:
    """指定バージョンからファイルを復元"""

# 履歴削除
@router.delete("/servers/{server_id}/files/{file_path:path}/history/{version}")
async def delete_file_version(
    server_id: int,
    file_path: str,
    version: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> DeleteVersionResponse:
    """特定バージョンを削除"""

# サーバー全体の編集履歴統計
@router.get("/servers/{server_id}/files/history/statistics")
async def get_server_file_history_stats(
    server_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> ServerFileHistoryStatsResponse:
    """サーバーのファイル編集履歴統計"""
```

### 6. レスポンススキーマ

```python
class FileHistoryRecord(BaseModel):
    id: int
    server_id: int
    file_path: str
    version_number: int
    file_size: int
    content_hash: str
    editor_user_id: Optional[int]
    editor_username: Optional[str]
    created_at: datetime
    description: Optional[str]

class FileHistoryListResponse(BaseModel):
    file_path: str
    total_versions: int
    history: List[FileHistoryRecord]

class FileVersionContentResponse(BaseModel):
    file_path: str
    version_number: int
    content: str
    encoding: str
    created_at: datetime
    editor_username: Optional[str]

class RestoreFromVersionRequest(BaseModel):
    create_backup_before_restore: bool = Field(True, description="復元前に現在の内容をバックアップ")
    description: Optional[str] = Field(None, description="復元操作の説明")

class ServerFileHistoryStatsResponse(BaseModel):
    server_id: int
    total_files_with_history: int
    total_versions: int
    total_storage_used: int  # bytes
    oldest_version_date: Optional[datetime]
    most_edited_file: Optional[str]
    most_edited_file_versions: Optional[int]
```

## 🔄 **既存機能との統合**

### 7. ファイル編集機能の修正

```python
# app/services/file_management_service.py の write_file_content を修正

async def write_file_content(
    self,
    file_path: Path,
    content: str,
    encoding: str = "utf-8",
    create_backup: bool = True,
    user_id: int = None,
    description: str = None
) -> Optional[FileHistoryRecord]:
    """ファイル内容書き込み（履歴管理付き）"""
    
    backup_record = None
    
    if create_backup and file_path.exists():
        # 現在のファイル内容を読み取り
        async with aiofiles.open(file_path, mode="r", encoding=encoding) as f:
            current_content = await f.read()
        
        # 新しい履歴サービスでバックアップ作成
        server_id = self._extract_server_id_from_path(file_path)  # パスからサーバーID抽出
        relative_path = self._get_relative_path(file_path, server_id)
        
        backup_record = await self.history_service.create_version_backup(
            server_id=server_id,
            file_path=relative_path,
            content=current_content,
            user_id=user_id,
            description=description
        )
    
    # ファイル書き込み
    file_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(file_path, mode="w", encoding=encoding) as f:
        await f.write(content)
    
    return backup_record
```

## 🧹 **管理機能**

### 8. 自動クリーンアップ機能

```python
class FileHistoryCleanupService:
    """ファイル履歴の自動クリーンアップ"""
    
    async def daily_cleanup_task(self):
        """日次クリーンアップタスク"""
        
        # 1. 古い履歴の削除（30日以上）
        await self._cleanup_old_versions()
        
        # 2. ファイルごとの最大バージョン数制限
        await self._cleanup_excess_versions()
        
        # 3. 孤立ファイルの削除
        await self._cleanup_orphaned_files()
        
        # 4. 重複コンテンツの統合
        await self._deduplicate_content()

    async def _cleanup_old_versions(self):
        """30日以上前の履歴を削除"""
        cutoff_date = datetime.now() - timedelta(days=30)
        
        old_records = await self.db.query(FileEditHistory).filter(
            FileEditHistory.created_at < cutoff_date
        ).all()
        
        for record in old_records:
            # ファイル削除
            backup_path = Path(record.backup_file_path)
            if backup_path.exists():
                backup_path.unlink()
            
            # DB記録削除
            await self.db.delete(record)

    async def _cleanup_excess_versions(self):
        """ファイルごとの最大バージョン数を維持"""
        # 各ファイルで50バージョンを超える場合、古いものから削除
```

### 9. 統計・監視機能

```python
class FileHistoryStatsService:
    """ファイル履歴の統計情報"""
    
    async def get_server_stats(self, server_id: int) -> ServerFileHistoryStats:
        """サーバーの編集履歴統計"""
        
        stats = await self.db.query(
            func.count(FileEditHistory.id).label('total_versions'),
            func.count(func.distinct(FileEditHistory.file_path)).label('total_files'),
            func.sum(FileEditHistory.file_size).label('total_storage'),
            func.min(FileEditHistory.created_at).label('oldest_version'),
            func.max(FileEditHistory.created_at).label('newest_version')
        ).filter(FileEditHistory.server_id == server_id).first()
        
        # 最も編集されたファイル
        most_edited = await self.db.query(
            FileEditHistory.file_path,
            func.count(FileEditHistory.id).label('version_count')
        ).filter(FileEditHistory.server_id == server_id)\
         .group_by(FileEditHistory.file_path)\
         .order_by(desc('version_count'))\
         .first()
        
        return ServerFileHistoryStats(
            server_id=server_id,
            total_versions=stats.total_versions or 0,
            total_files_with_history=stats.total_files or 0,
            total_storage_used=stats.total_storage or 0,
            oldest_version_date=stats.oldest_version,
            most_edited_file=most_edited.file_path if most_edited else None,
            most_edited_file_versions=most_edited.version_count if most_edited else None
        )
```

## 🔐 **セキュリティ・権限**

### 10. アクセス制御

```python
class FileHistoryAuthorizationService:
    """ファイル履歴のアクセス制御"""
    
    def can_view_file_history(self, user: User, server_id: int) -> bool:
        """ファイル履歴の閲覧権限"""
        return self.authorization_service.check_server_access(server_id, user)
    
    def can_restore_from_history(self, user: User, server_id: int) -> bool:
        """履歴からの復元権限"""
        # オペレーター以上のみ復元可能
        return user.role.value in ["admin", "operator"] and \
               self.authorization_service.check_server_access(server_id, user)
    
    def can_delete_history(self, user: User, server_id: int) -> bool:
        """履歴削除権限"""
        # 管理者のみ履歴削除可能
        return user.role.value == "admin"
```

## 📈 **設計の利点**

### 11. この設計の優位性

1. **整理された管理**
   - ファイル履歴が専用ディレクトリに分離
   - サーバーディレクトリがクリーンに保たれる

2. **スケーラビリティ**
   - サーバー数、ファイル数の増加に対応
   - バージョン数制限による容量管理

3. **ユーザビリティ**
   - 直感的な履歴参照
   - 簡単な復元操作
   - 編集者情報の追跡

4. **パフォーマンス**
   - インデックス最適化
   - 重複コンテンツの削除
   - 自動クリーンアップ

5. **拡張性**
   - 将来的な差分表示機能
   - ブランチ・マージ機能
   - コメント・アノテーション機能

## 🚀 **マイグレーション戦略**

### 12. 既存データの移行

```python
class FileHistoryMigrationService:
    """既存のbackupファイルを新システムに移行"""
    
    async def migrate_existing_backups(self):
        """
        1. servers/内の *.backup_* ファイルを検出
        2. 新しいディレクトリ構造に移動
        3. データベース記録作成
        4. 元ファイル削除
        """
```

## 📝 **実装順序**

1. データベースモデル作成
2. FileHistoryService実装
3. 既存ファイル編集機能の修正
4. API endpoints実装
5. 自動クリーンアップ機能
6. 統計・監視機能
7. マイグレーション実行

---

**作成日時**: 2025年6月10日  
**バージョン**: 1.0  
**ステータス**: 設計完了・実装準備完了