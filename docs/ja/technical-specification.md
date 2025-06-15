# Minecraft Server Dashboard API V2 - 技術仕様書

## 概要

この文書は、Minecraft Server Dashboard API V2を実装するための詳細な技術仕様を提供します。アーキテクチャ設計に基づいた具体的な実装パターン、コード例、段階的な開発ガイドラインが含まれています。

## プロジェクト構造

### ルートディレクトリ構造
```
mc-server-dashboard-api-v2/
├── pyproject.toml
├── uv.lock
├── README.md
├── CHANGELOG.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── shared/
│   ├── users/
│   ├── servers/
│   ├── groups/
│   ├── backups/
│   ├── files/
│   ├── monitoring/
│   └── migrations/
├── tests/
├── docs/
├── scripts/
└── deployment/
```

### ドメインモジュール構造テンプレート
```
{domain}/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── entities/
│   │   ├── __init__.py
│   │   └── {entity}.py
│   ├── value_objects/
│   │   ├── __init__.py
│   │   └── {value_object}.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── {entity}_repository.py
│   ├── events/
│   │   ├── __init__.py
│   │   └── {event}.py
│   ├── services/
│   │   ├── __init__.py
│   │   └── {service}.py
│   └── exceptions/
│       ├── __init__.py
│       └── {domain}_exceptions.py
├── application/
│   ├── __init__.py
│   ├── commands/
│   │   ├── __init__.py
│   │   └── {command}.py
│   ├── queries/
│   │   ├── __init__.py
│   │   └── {query}.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── command_handlers.py
│   │   └── query_handlers.py
│   └── dto/
│       ├── __init__.py
│       └── {dto}.py
├── infrastructure/
│   ├── __init__.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── sql_{entity}_repository.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   └── {adapter}.py
│   └── external/
│       ├── __init__.py
│       └── {external_service}.py
└── api/
    ├── __init__.py
    ├── router.py
    ├── schemas.py
    └── dependencies.py
```

## コア実装パターン

### 1. エンティティパターン

#### ベースエンティティ
```python
# app/shared/domain/entities/base_entity.py
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from app.shared.domain.events.domain_event import DomainEvent


@dataclass
class BaseEntity(ABC):
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    version: int = 1
    _domain_events: List[DomainEvent] = field(default_factory=list, init=False)
    
    def add_domain_event(self, event: DomainEvent) -> None:
        """ドメインイベントを発行するために追加する。"""
        self._domain_events.append(event)
    
    def clear_domain_events(self) -> None:
        """発行後にドメインイベントをクリアする。"""
        self._domain_events.clear()
    
    def get_domain_events(self) -> List[DomainEvent]:
        """保留中のすべてのドメインイベントを取得する。"""
        return self._domain_events.copy()
    
    def mark_as_updated(self) -> None:
        """エンティティを更新済みとしてマークする。"""
        self.updated_at = datetime.utcnow()
        self.version += 1


# エンティティ実装例
# app/servers/domain/entities/minecraft_server.py
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from app.shared.domain.entities.base_entity import BaseEntity
from app.servers.domain.value_objects.server_id import ServerId
from app.servers.domain.value_objects.port import Port
from app.servers.domain.events.server_created import ServerCreated
from app.servers.domain.events.server_started import ServerStarted


class ServerStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting" 
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


@dataclass
class MinecraftServer(BaseEntity):
    name: str
    description: Optional[str]
    owner_id: UUID
    port: Port
    status: ServerStatus = ServerStatus.STOPPED
    minecraft_version: str = "1.21.5"
    memory_mb: int = 2048
    java_args: str = "-XX:+UseG1GC"
    
    def __post_init__(self):
        if not hasattr(self, '_initialized'):
            self.add_domain_event(
                ServerCreated(
                    server_id=self.id,
                    name=self.name,
                    owner_id=self.owner_id,
                    occurred_at=self.created_at
                )
            )
            self._initialized = True
    
    def start(self) -> None:
        """Minecraftサーバーを起動する。"""
        if self.status != ServerStatus.STOPPED:
            raise ValueError(f"{self.status}状態のサーバーは起動できません")
        
        self.status = ServerStatus.STARTING
        self.mark_as_updated()
        
        self.add_domain_event(
            ServerStarted(
                server_id=self.id,
                occurred_at=datetime.utcnow()
            )
        )
    
    def stop(self) -> None:
        """Minecraftサーバーを停止する。"""
        if self.status not in [ServerStatus.RUNNING, ServerStatus.STARTING]:
            raise ValueError(f"{self.status}状態のサーバーは停止できません")
        
        self.status = ServerStatus.STOPPING
        self.mark_as_updated()
    
    def update_configuration(self, memory_mb: Optional[int] = None, 
                           java_args: Optional[str] = None) -> None:
        """サーバー設定を更新する。"""
        if memory_mb is not None:
            if memory_mb < 512 or memory_mb > 32768:
                raise ValueError("メモリは512MBから32GBの間である必要があります")
            self.memory_mb = memory_mb
        
        if java_args is not None:
            self.java_args = java_args
        
        self.mark_as_updated()
```

### 2. 値オブジェクトパターン

```python
# app/shared/domain/value_objects/base_value_object.py
from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class BaseValueObject(ABC):
    """すべての値オブジェクトの基底クラス。"""
    pass


# app/servers/domain/value_objects/port.py
from dataclasses import dataclass

from app.shared.domain.value_objects.base_value_object import BaseValueObject


@dataclass(frozen=True)
class Port(BaseValueObject):
    value: int
    
    def __post_init__(self):
        if not isinstance(self.value, int):
            raise ValueError("ポートは整数である必要があります")
        if not (1024 <= self.value <= 65535):
            raise ValueError("ポートは1024から65535の間である必要があります")
    
    def __str__(self) -> str:
        return str(self.value)
    
    def __int__(self) -> int:
        return self.value


# app/users/domain/value_objects/email.py
import re
from dataclasses import dataclass

from app.shared.domain.value_objects.base_value_object import BaseValueObject


@dataclass(frozen=True)
class Email(BaseValueObject):
    value: str
    
    def __post_init__(self):
        if not self._is_valid_email(self.value):
            raise ValueError("無効なメールアドレス形式です")
    
    @staticmethod
    def _is_valid_email(email: str) -> bool:
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def __str__(self) -> str:
        return self.value
```

### 3. ドメインイベントパターン

```python
# app/shared/domain/events/domain_event.py
from abc import ABC
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class DomainEvent(ABC):
    """すべてのドメインイベントの基底クラス。"""
    event_id: UUID = uuid4()
    occurred_at: datetime = datetime.utcnow()
    
    @property
    def event_type(self) -> str:
        """イベントタイプ名を取得する。"""
        return self.__class__.__name__


# app/servers/domain/events/server_created.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.shared.domain.events.domain_event import DomainEvent


@dataclass
class ServerCreated(DomainEvent):
    server_id: UUID
    name: str
    owner_id: UUID
    minecraft_version: str
    
    @property
    def aggregate_id(self) -> UUID:
        return self.server_id


# app/servers/domain/events/server_started.py
from dataclasses import dataclass
from uuid import UUID

from app.shared.domain.events.domain_event import DomainEvent


@dataclass
class ServerStarted(DomainEvent):
    server_id: UUID
    
    @property
    def aggregate_id(self) -> UUID:
        return self.server_id
```

### 4. リポジトリパターン

```python
# app/shared/domain/repositories/base_repository.py
from abc import ABC, abstractmethod
from typing import List, Optional, Generic, TypeVar
from uuid import UUID

T = TypeVar('T')


class BaseRepository(Generic[T], ABC):
    """基底リポジトリインターフェース。"""
    
    @abstractmethod
    async def get_by_id(self, id: UUID) -> Optional[T]:
        """IDでエンティティを取得する。"""
        pass
    
    @abstractmethod
    async def save(self, entity: T) -> T:
        """エンティティを保存する。"""
        pass
    
    @abstractmethod
    async def delete(self, id: UUID) -> None:
        """IDでエンティティを削除する。"""
        pass
    
    @abstractmethod
    async def list(self, limit: int = 100, offset: int = 0) -> List[T]:
        """ページネーション付きでエンティティをリストする。"""
        pass


# app/servers/domain/repositories/server_repository.py
from abc import abstractmethod
from typing import List, Optional
from uuid import UUID

from app.shared.domain.repositories.base_repository import BaseRepository
from app.servers.domain.entities.minecraft_server import MinecraftServer
from app.servers.domain.value_objects.port import Port


class ServerRepository(BaseRepository[MinecraftServer]):
    """MinecraftServerエンティティのリポジトリインターフェース。"""
    
    @abstractmethod
    async def find_by_owner(self, owner_id: UUID) -> List[MinecraftServer]:
        """オーナーIDでサーバーを検索する。"""
        pass
    
    @abstractmethod
    async def find_by_port(self, port: Port) -> Optional[MinecraftServer]:
        """ポートでサーバーを検索する。"""
        pass
    
    @abstractmethod
    async def is_port_available(self, port: Port, exclude_server_id: Optional[UUID] = None) -> bool:
        """ポートが利用可能かチェックする。"""
        pass
```

### 5. コマンドパターン

```python
# app/shared/application/commands/command.py
from abc import ABC
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class Command(ABC):
    """すべてのコマンドの基底クラス。"""
    command_id: UUID = uuid4()
    created_at: datetime = datetime.utcnow()


# app/servers/application/commands/create_server.py
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.shared.application.commands.command import Command


@dataclass
class CreateServerCommand(Command):
    name: str
    description: Optional[str]
    owner_id: UUID
    minecraft_version: str
    memory_mb: int
    port: Optional[int] = None  # Noneの場合は自動割り当て


@dataclass
class StartServerCommand(Command):
    server_id: UUID


@dataclass
class StopServerCommand(Command):
    server_id: UUID
```

### 6. クエリパターン

```python
# app/shared/application/queries/query.py
from abc import ABC
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4


@dataclass
class Query(ABC):
    """すべてのクエリの基底クラス。"""
    query_id: UUID = uuid4()
    created_at: datetime = datetime.utcnow()


# app/servers/application/queries/get_server_list.py
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.shared.application.queries.query import Query


@dataclass
class GetServerListQuery(Query):
    owner_id: Optional[UUID] = None
    status: Optional[str] = None
    page: int = 1
    limit: int = 20


@dataclass
class GetServerDetailsQuery(Query):
    server_id: UUID
    include_metrics: bool = False
```

### 7. コマンドハンドラーパターン

```python
# app/shared/application/handlers/base_handler.py
from abc import ABC, abstractmethod
from typing import TypeVar, Generic

from app.shared.application.commands.command import Command
from app.shared.application.queries.query import Query

CommandT = TypeVar('CommandT', bound=Command)
QueryT = TypeVar('QueryT', bound=Query)
ResultT = TypeVar('ResultT')


class CommandHandler(Generic[CommandT], ABC):
    """コマンドハンドラーの基底クラス。"""
    
    @abstractmethod
    async def handle(self, command: CommandT) -> None:
        """コマンドを処理する。"""
        pass


class QueryHandler(Generic[QueryT, ResultT], ABC):
    """クエリハンドラーの基底クラス。"""
    
    @abstractmethod
    async def handle(self, query: QueryT) -> ResultT:
        """クエリを処理して結果を返す。"""
        pass


# app/servers/application/handlers/server_command_handlers.py
from uuid import UUID

from app.shared.application.handlers.base_handler import CommandHandler
from app.shared.infrastructure.database.unit_of_work import UnitOfWork
from app.shared.infrastructure.events.event_publisher import EventPublisher
from app.servers.application.commands.create_server import CreateServerCommand
from app.servers.application.commands.start_server import StartServerCommand
from app.servers.domain.entities.minecraft_server import MinecraftServer
from app.servers.domain.value_objects.port import Port
from app.servers.domain.repositories.server_repository import ServerRepository
from app.servers.domain.services.port_service import PortService


class CreateServerCommandHandler(CommandHandler[CreateServerCommand]):
    def __init__(
        self,
        server_repository: ServerRepository,
        port_service: PortService,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher
    ):
        self._server_repository = server_repository
        self._port_service = port_service
        self._unit_of_work = unit_of_work
        self._event_publisher = event_publisher
    
    async def handle(self, command: CreateServerCommand) -> UUID:
        async with self._unit_of_work:
            # ポートが提供されていない場合は割り当てる
            if command.port is None:
                port = await self._port_service.find_available_port()
            else:
                port = Port(command.port)
                if not await self._server_repository.is_port_available(port):
                    raise ValueError(f"ポート {port} は既に使用されています")
            
            # サーバーエンティティを作成
            server = MinecraftServer(
                name=command.name,
                description=command.description,
                owner_id=command.owner_id,
                port=port,
                minecraft_version=command.minecraft_version,
                memory_mb=command.memory_mb
            )
            
            # サーバーを保存
            await self._server_repository.save(server)
            
            # ドメインイベントを発行
            for event in server.get_domain_events():
                await self._event_publisher.publish(event)
            
            server.clear_domain_events()
            
            await self._unit_of_work.commit()
            
            return server.id


class StartServerCommandHandler(CommandHandler[StartServerCommand]):
    def __init__(
        self,
        server_repository: ServerRepository,
        unit_of_work: UnitOfWork,
        event_publisher: EventPublisher
    ):
        self._server_repository = server_repository
        self._unit_of_work = unit_of_work
        self._event_publisher = event_publisher
    
    async def handle(self, command: StartServerCommand) -> None:
        async with self._unit_of_work:
            server = await self._server_repository.get_by_id(command.server_id)
            if server is None:
                raise ValueError(f"サーバー {command.server_id} が見つかりません")
            
            server.start()
            await self._server_repository.save(server)
            
            # ドメインイベントを発行
            for event in server.get_domain_events():
                await self._event_publisher.publish(event)
            
            server.clear_domain_events()
            
            await self._unit_of_work.commit()
```

### 8. SQLAlchemyリポジトリ実装

```python
# app/shared/infrastructure/database/models.py
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


class BaseModel:
    """共通フィールドを持つ基底モデル。"""
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    version = Column(Integer, default=1)


# app/servers/infrastructure/database/models.py
from sqlalchemy import Column, String, Integer, Enum, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship

from app.shared.infrastructure.database.models import Base, BaseModel
from app.servers.domain.entities.minecraft_server import ServerStatus


class ServerModel(Base, BaseModel):
    __tablename__ = "servers"
    
    name = Column(String(100), nullable=False)
    description = Column(Text)
    owner_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    port = Column(Integer, unique=True, nullable=False)
    status = Column(Enum(ServerStatus), default=ServerStatus.STOPPED)
    minecraft_version = Column(String(20), nullable=False)
    memory_mb = Column(Integer, nullable=False)
    java_args = Column(String(500))
    configuration = Column(JSONB)
    
    # リレーションシップ
    owner = relationship("UserModel", back_populates="servers")
    backups = relationship("BackupModel", back_populates="server")


# app/servers/infrastructure/repositories/sql_server_repository.py
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.servers.domain.entities.minecraft_server import MinecraftServer, ServerStatus
from app.servers.domain.repositories.server_repository import ServerRepository
from app.servers.domain.value_objects.port import Port
from app.servers.infrastructure.database.models import ServerModel


class SqlServerRepository(ServerRepository):
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def get_by_id(self, id: UUID) -> Optional[MinecraftServer]:
        result = await self._session.execute(
            select(ServerModel).where(ServerModel.id == id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None
    
    async def save(self, entity: MinecraftServer) -> MinecraftServer:
        model = await self._session.get(ServerModel, entity.id)
        if model is None:
            model = ServerModel()
        
        self._update_model_from_entity(model, entity)
        self._session.add(model)
        await self._session.flush()
        
        return self._to_entity(model)
    
    async def delete(self, id: UUID) -> None:
        result = await self._session.execute(
            select(ServerModel).where(ServerModel.id == id)
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
    
    async def list(self, limit: int = 100, offset: int = 0) -> List[MinecraftServer]:
        result = await self._session.execute(
            select(ServerModel).offset(offset).limit(limit)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]
    
    async def find_by_owner(self, owner_id: UUID) -> List[MinecraftServer]:
        result = await self._session.execute(
            select(ServerModel).where(ServerModel.owner_id == owner_id)
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]
    
    async def find_by_port(self, port: Port) -> Optional[MinecraftServer]:
        result = await self._session.execute(
            select(ServerModel).where(ServerModel.port == port.value)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None
    
    async def is_port_available(self, port: Port, exclude_server_id: Optional[UUID] = None) -> bool:
        query = select(ServerModel).where(ServerModel.port == port.value)
        if exclude_server_id:
            query = query.where(ServerModel.id != exclude_server_id)
        
        result = await self._session.execute(query)
        return result.scalar_one_or_none() is None
    
    def _to_entity(self, model: ServerModel) -> MinecraftServer:
        """SQLAlchemyモデルをドメインエンティティに変換する。"""
        return MinecraftServer(
            id=model.id,
            name=model.name,
            description=model.description,
            owner_id=model.owner_id,
            port=Port(model.port),
            status=model.status,
            minecraft_version=model.minecraft_version,
            memory_mb=model.memory_mb,
            java_args=model.java_args or "",
            created_at=model.created_at,
            updated_at=model.updated_at,
            version=model.version
        )
    
    def _update_model_from_entity(self, model: ServerModel, entity: MinecraftServer) -> None:
        """ドメインエンティティからSQLAlchemyモデルを更新する。"""
        model.id = entity.id
        model.name = entity.name
        model.description = entity.description
        model.owner_id = entity.owner_id
        model.port = entity.port.value
        model.status = entity.status
        model.minecraft_version = entity.minecraft_version
        model.memory_mb = entity.memory_mb
        model.java_args = entity.java_args
        model.version = entity.version
```

### 9. ユニットオブワークパターン

```python
# app/shared/infrastructure/database/unit_of_work.py
from abc import ABC, abstractmethod
from typing import AsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork(ABC):
    """ユニットオブワークインターフェース。"""
    
    @abstractmethod
    async def commit(self) -> None:
        """トランザクションをコミットする。"""
        pass
    
    @abstractmethod
    async def rollback(self) -> None:
        """トランザクションをロールバックする。"""
        pass
    
    @abstractmethod
    async def __aenter__(self):
        """非同期コンテキストに入る。"""
        pass
    
    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストから出る。"""
        pass


class SqlUnitOfWork(UnitOfWork):
    """SQLAlchemyユニットオブワーク実装。"""
    
    def __init__(self, session: AsyncSession):
        self._session = session
    
    async def commit(self) -> None:
        await self._session.commit()
    
    async def rollback(self) -> None:
        await self._session.rollback()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
```

### 10. イベント発行パターン

```python
# app/shared/infrastructure/events/event_publisher.py
from abc import ABC, abstractmethod
from typing import List

from app.shared.domain.events.domain_event import DomainEvent


class EventPublisher(ABC):
    """イベント発行インターフェース。"""
    
    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        """単一のイベントを発行する。"""
        pass
    
    @abstractmethod
    async def publish_many(self, events: List[DomainEvent]) -> None:
        """複数のイベントを発行する。"""
        pass


# app/shared/infrastructure/events/redis_event_publisher.py
import json
from typing import List

import redis.asyncio as redis

from app.shared.domain.events.domain_event import DomainEvent
from app.shared.infrastructure.events.event_publisher import EventPublisher


class RedisEventPublisher(EventPublisher):
    """Redisベースのイベント発行。"""
    
    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client
    
    async def publish(self, event: DomainEvent) -> None:
        channel = f"events:{event.event_type}"
        message = self._serialize_event(event)
        await self._redis.publish(channel, message)
    
    async def publish_many(self, events: List[DomainEvent]) -> None:
        pipe = self._redis.pipeline()
        for event in events:
            channel = f"events:{event.event_type}"
            message = self._serialize_event(event)
            pipe.publish(channel, message)
        await pipe.execute()
    
    def _serialize_event(self, event: DomainEvent) -> str:
        """イベントをJSONにシリアライズする。"""
        event_dict = {
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat(),
            "data": event.__dict__
        }
        return json.dumps(event_dict)
```

### 11. FastAPIルーター実装

```python
# app/servers/api/schemas.py
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, validator
import re


class CreateServerRequest(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)
    description: Optional[str] = Field(None, max_length=500)
    minecraft_version: str = Field(..., regex=r'^\d+\.\d+(\.\d+)?$')
    memory_mb: int = Field(..., ge=512, le=32768)
    port: Optional[int] = Field(None, ge=1024, le=65535)
    
    @validator('name')
    def validate_server_name(cls, v):
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError('サーバー名は英数字、アンダースコア、ハイフンのみ使用可能です')
        return v


class ServerResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    owner_id: UUID
    port: int
    status: str
    minecraft_version: str
    memory_mb: int
    created_at: datetime
    updated_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class ServerListResponse(BaseModel):
    servers: List[ServerResponse]
    total: int
    page: int
    limit: int


# app/servers/api/dependencies.py
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.infrastructure.database.session import get_db_session
from app.servers.infrastructure.repositories.sql_server_repository import SqlServerRepository
from app.servers.application.handlers.server_command_handlers import CreateServerCommandHandler


async def get_server_repository(
    session: AsyncSession = Depends(get_db_session)
) -> SqlServerRepository:
    return SqlServerRepository(session)


async def get_create_server_handler(
    server_repository: SqlServerRepository = Depends(get_server_repository),
    # ... その他の依存関係
) -> CreateServerCommandHandler:
    return CreateServerCommandHandler(
        server_repository=server_repository,
        # ... その他の依存関係
    )


# app/servers/api/router.py
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer

from app.shared.api.dependencies import get_current_user
from app.servers.api.schemas import CreateServerRequest, ServerResponse, ServerListResponse
from app.servers.api.dependencies import get_create_server_handler
from app.servers.application.commands.create_server import CreateServerCommand
from app.servers.application.handlers.server_command_handlers import CreateServerCommandHandler

router = APIRouter(prefix="/api/v2/servers", tags=["servers"])
security = HTTPBearer()


@router.post("/", response_model=ServerResponse, status_code=status.HTTP_201_CREATED)
async def create_server(
    request: CreateServerRequest,
    current_user = Depends(get_current_user),
    handler: CreateServerCommandHandler = Depends(get_create_server_handler)
):
    """新しいMinecraftサーバーを作成する。"""
    command = CreateServerCommand(
        name=request.name,
        description=request.description,
        owner_id=current_user.id,
        minecraft_version=request.minecraft_version,
        memory_mb=request.memory_mb,
        port=request.port
    )
    
    try:
        server_id = await handler.handle(command)
        # 作成されたサーバーを返す（ここではクエリハンドラーが必要）
        return {"message": "サーバーが作成されました", "id": server_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="内部サーバーエラー")


@router.get("/", response_model=ServerListResponse)
async def list_servers(
    page: int = 1,
    limit: int = 20,
    current_user = Depends(get_current_user),
    # query_handler = Depends(get_server_list_query_handler)
):
    """ユーザーのサーバーをリストする。"""
    # 実装ではクエリハンドラーを使用
    pass


@router.get("/{server_id}", response_model=ServerResponse)
async def get_server(
    server_id: UUID,
    current_user = Depends(get_current_user),
    # query_handler = Depends(get_server_details_query_handler)
):
    """サーバーの詳細を取得する。"""
    # 実装ではクエリハンドラーを使用
    pass


@router.post("/{server_id}/start")
async def start_server(
    server_id: UUID,
    current_user = Depends(get_current_user),
    # handler = Depends(get_start_server_handler)
):
    """サーバーを起動する。"""
    # 実装ではコマンドハンドラーを使用
    pass


@router.post("/{server_id}/stop")
async def stop_server(
    server_id: UUID,
    current_user = Depends(get_current_user),
    # handler = Depends(get_stop_server_handler)
):
    """サーバーを停止する。"""
    # 実装ではコマンドハンドラーを使用
    pass
```

### 12. バックグラウンドジョブ処理

```python
# app/shared/infrastructure/jobs/job_queue.py
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from uuid import UUID


class JobQueue(ABC):
    """ジョブキューインターフェース。"""
    
    @abstractmethod
    async def enqueue(
        self, 
        job_name: str, 
        *args, 
        queue: str = "default",
        delay: Optional[int] = None,
        **kwargs
    ) -> str:
        """ジョブをエンキューする。"""
        pass
    
    @abstractmethod
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """ジョブステータスを取得する。"""
        pass


# app/shared/infrastructure/jobs/rq_job_queue.py
from typing import Any, Dict, Optional

import rq
from rq.job import Job

from app.shared.infrastructure.jobs.job_queue import JobQueue


class RQJobQueue(JobQueue):
    """RQベースのジョブキュー実装。"""
    
    def __init__(self, redis_connection):
        self._redis = redis_connection
        self._queues = {
            "high_priority": rq.Queue("high_priority", connection=redis_connection),
            "default": rq.Queue("default", connection=redis_connection),
            "low_priority": rq.Queue("low_priority", connection=redis_connection)
        }
    
    async def enqueue(
        self, 
        job_name: str, 
        *args, 
        queue: str = "default",
        delay: Optional[int] = None,
        **kwargs
    ) -> str:
        q = self._queues.get(queue, self._queues["default"])
        
        if delay:
            job = q.enqueue_in(delay, job_name, *args, **kwargs)
        else:
            job = q.enqueue(job_name, *args, **kwargs)
        
        return job.id
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        job = Job.fetch(job_id, connection=self._redis)
        return {
            "id": job.id,
            "status": job.get_status(),
            "result": job.result,
            "exc_info": job.exc_info,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "ended_at": job.ended_at
        }


# app/servers/infrastructure/jobs/server_jobs.py
import asyncio
import subprocess
from uuid import UUID

from app.servers.domain.repositories.server_repository import ServerRepository
from app.shared.infrastructure.events.event_publisher import EventPublisher


async def start_server_process(server_id: UUID):
    """Minecraftサーバープロセスを起動するバックグラウンドジョブ。"""
    # これはワーカー関数として実装される
    # 実際にサーバープロセスを起動する
    
    # 1. リポジトリからサーバー詳細を取得
    # 2. サーバーディレクトリが存在しない場合は作成
    # 3. 必要に応じてサーバーJARをダウンロード
    # 4. 適切なJava引数でプロセスを起動
    # 5. 起動を監視してステータスを更新
    # 6. 起動結果に基づいてイベントを発行
    
    pass


async def stop_server_process(server_id: UUID):
    """Minecraftサーバープロセスを停止するバックグラウンドジョブ。"""
    # 1. サーバーコンソールに停止コマンドを送信
    # 2. グレースフルシャットダウンを待つ
    # 3. タイムアウト超過時は強制終了
    # 4. サーバーステータスを更新
    # 5. イベントを発行
    pass


async def create_backup_job(server_id: UUID, backup_name: str):
    """サーバーバックアップを作成するバックグラウンドジョブ。"""
    # 1. サーバーが実行中かチェック
    # 2. 実行中の場合はsave-allコマンドを送信
    # 3. サーバーディレクトリの圧縮アーカイブを作成
    # 4. データベースにバックアップメタデータを保存
    # 5. バックアップ作成イベントを発行
    pass
```

### 13. 設定管理

```python
# app/config.py
from functools import lru_cache
from typing import Optional

from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    """アプリケーション設定。"""
    
    # データベース
    database_url: str = Field(..., env="DATABASE_URL")
    database_pool_size: int = Field(10, env="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(20, env="DATABASE_MAX_OVERFLOW")
    
    # Redis
    redis_url: str = Field("redis://localhost:6379", env="REDIS_URL")
    
    # セキュリティ
    secret_key: str = Field(..., env="SECRET_KEY")
    algorithm: str = Field("HS256", env="ALGORITHM")
    access_token_expire_minutes: int = Field(30, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(7, env="REFRESH_TOKEN_EXPIRE_DAYS")
    
    # サーバー管理
    servers_directory: str = Field("./servers", env="SERVERS_DIRECTORY")
    backups_directory: str = Field("./backups", env="BACKUPS_DIRECTORY")
    templates_directory: str = Field("./templates", env="TEMPLATES_DIRECTORY")
    cache_directory: str = Field("./cache", env="CACHE_DIRECTORY")
    
    # Java
    java_path: Optional[str] = Field(None, env="JAVA_PATH")
    default_java_args: str = Field("-XX:+UseG1GC -XX:+ParallelRefProcEnabled", env="DEFAULT_JAVA_ARGS")
    
    # 監視
    enable_metrics: bool = Field(True, env="ENABLE_METRICS")
    metrics_retention_days: int = Field(30, env="METRICS_RETENTION_DAYS")
    
    # レート制限
    rate_limit_per_minute: int = Field(100, env="RATE_LIMIT_PER_MINUTE")
    
    # ファイル管理
    max_file_size_mb: int = Field(100, env="MAX_FILE_SIZE_MB")
    allowed_file_extensions: list = Field(
        [".txt", ".properties", ".yml", ".yaml", ".json", ".conf"],
        env="ALLOWED_FILE_EXTENSIONS"
    )
    
    @validator("database_url")
    def validate_database_url(cls, v):
        if not v.startswith(("postgresql://", "sqlite:///")):
            raise ValueError("データベースURLはPostgreSQLまたはSQLiteである必要があります")
        return v
    
    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """キャッシュされた設定インスタンスを取得する。"""
    return Settings()
```

### 14. テストパターン

```python
# tests/conftest.py
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.shared.infrastructure.database.models import Base
from app.config import get_settings


@pytest.fixture(scope="session")
def event_loop():
    """テストセッション用のデフォルトイベントループのインスタンスを作成する。"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    """テストデータベースセッションを作成する。"""
    settings = get_settings()
    test_db_url = settings.database_url.replace("mcapi", "mcapi_test")
    
    engine = create_async_engine(test_db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        yield session
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session):
    """テストクライアントを作成する。"""
    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


# tests/unit/servers/domain/test_minecraft_server.py
import pytest
from uuid import uuid4

from app.servers.domain.entities.minecraft_server import MinecraftServer, ServerStatus
from app.servers.domain.value_objects.port import Port


class TestMinecraftServer:
    def test_create_server(self):
        """サーバー作成をテストする。"""
        server = MinecraftServer(
            name="test-server",
            description="テストサーバー",
            owner_id=uuid4(),
            port=Port(25565),
            minecraft_version="1.21.5",
            memory_mb=2048
        )
        
        assert server.name == "test-server"
        assert server.status == ServerStatus.STOPPED
        assert len(server.get_domain_events()) == 1
        assert server.get_domain_events()[0].event_type == "ServerCreated"
    
    def test_start_server(self):
        """サーバー起動をテストする。"""
        server = MinecraftServer(
            name="test-server",
            description="テストサーバー",
            owner_id=uuid4(),
            port=Port(25565)
        )
        
        server.clear_domain_events()  # 作成イベントをクリア
        server.start()
        
        assert server.status == ServerStatus.STARTING
        assert len(server.get_domain_events()) == 1
        assert server.get_domain_events()[0].event_type == "ServerStarted"
    
    def test_cannot_start_running_server(self):
        """実行中のサーバーを起動できないことをテストする。"""
        server = MinecraftServer(
            name="test-server",
            description="テストサーバー",
            owner_id=uuid4(),
            port=Port(25565)
        )
        
        server.start()
        
        with pytest.raises(ValueError, match="starting状態のサーバーは起動できません"):
            server.start()


# tests/integration/servers/test_server_api.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_server(client: AsyncClient, auth_headers):
    """API経由でのサーバー作成をテストする。"""
    server_data = {
        "name": "test-server",
        "description": "テストサーバー",
        "minecraft_version": "1.21.5",
        "memory_mb": 2048
    }
    
    response = await client.post(
        "/api/v2/servers/",
        json=server_data,
        headers=auth_headers
    )
    
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "test-server"
    assert data["status"] == "stopped"


@pytest.mark.asyncio
async def test_create_server_invalid_name(client: AsyncClient, auth_headers):
    """無効な名前でのサーバー作成をテストする。"""
    server_data = {
        "name": "test server!",  # 無効な文字
        "minecraft_version": "1.21.5",
        "memory_mb": 2048
    }
    
    response = await client.post(
        "/api/v2/servers/",
        json=server_data,
        headers=auth_headers
    )
    
    assert response.status_code == 422


# tests/e2e/test_server_lifecycle.py
@pytest.mark.asyncio
async def test_complete_server_lifecycle(client: AsyncClient, auth_headers):
    """作成から削除までの完全なサーバーライフサイクルをテストする。"""
    
    # サーバーを作成
    server_data = {
        "name": "lifecycle-test",
        "minecraft_version": "1.21.5",
        "memory_mb": 1024
    }
    
    create_response = await client.post(
        "/api/v2/servers/",
        json=server_data,
        headers=auth_headers
    )
    assert create_response.status_code == 201
    server_id = create_response.json()["id"]
    
    # サーバーを起動
    start_response = await client.post(
        f"/api/v2/servers/{server_id}/start",
        headers=auth_headers
    )
    assert start_response.status_code == 200
    
    # ステータスをチェック
    status_response = await client.get(
        f"/api/v2/servers/{server_id}",
        headers=auth_headers
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] in ["starting", "running"]
    
    # サーバーを停止
    stop_response = await client.post(
        f"/api/v2/servers/{server_id}/stop",
        headers=auth_headers
    )
    assert stop_response.status_code == 200
    
    # サーバーを削除
    delete_response = await client.delete(
        f"/api/v2/servers/{server_id}",
        headers=auth_headers
    )
    assert delete_response.status_code == 204
```

### 15. メインアプリケーションセットアップ

```python
# app/main.py
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import get_settings
from app.shared.api.middleware import (
    RequestLoggingMiddleware,
    PerformanceMiddleware,
    ErrorHandlingMiddleware
)
from app.shared.infrastructure.database.session import init_database
from app.shared.infrastructure.events.event_handlers import setup_event_handlers
from app.users.api.router import router as users_router
from app.servers.api.router import router as servers_router
from app.groups.api.router import router as groups_router
from app.backups.api.router import router as backups_router
from app.templates.api.router import router as templates_router
from app.files.api.router import router as files_router
from app.monitoring.api.router import router as monitoring_router

# ログ設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションライフスパンマネージャー。"""
    # 起動
    logger.info("Minecraft Server Dashboard API V2を起動中")
    
    # データベースを初期化
    await init_database()
    
    # イベントハンドラーを設定
    await setup_event_handlers()
    
    logger.info("アプリケーション起動完了")
    
    yield
    
    # シャットダウン
    logger.info("アプリケーションをシャットダウン中")


def create_app() -> FastAPI:
    """FastAPIアプリケーションを作成する。"""
    settings = get_settings()
    
    app = FastAPI(
        title="Minecraft Server Dashboard API V2",
        description="複数のMinecraftサーバーを管理するための包括的なAPI",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc"
    )
    
    # ミドルウェアを追加
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 本番環境では適切に設定
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(PerformanceMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    
    # ルーターを含める
    app.include_router(users_router)
    app.include_router(servers_router)
    app.include_router(groups_router)
    app.include_router(backups_router)
    app.include_router(templates_router)
    app.include_router(files_router)
    app.include_router(monitoring_router)
    
    return app


app = create_app()


@app.get("/")
async def root():
    """ルートエンドポイント。"""
    return {"message": "Minecraft Server Dashboard API V2"}


@app.get("/health")
async def health_check():
    """ヘルスチェックエンドポイント。"""
    return {"status": "healthy", "version": "2.0.0"}


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
```

## 開発ワークフロー

### 1. プロジェクトセットアップ
```bash
# プロジェクトを初期化
mkdir mc-server-dashboard-api-v2
cd mc-server-dashboard-api-v2

# UV環境をセットアップ
uv init
uv add fastapi[all] sqlalchemy[asyncio] asyncpg redis rq celery pydantic-settings structlog pytest pytest-asyncio httpx

# 基本構造を作成
mkdir -p app/{shared,users,servers,groups,backups,templates,files,monitoring}
mkdir -p tests/{unit,integration,e2e}
mkdir -p docs
mkdir -p scripts
```

### 2. 開発標準

#### コードスタイル
- Black formatterを使用（88文字の行長）
- Ruffを使用したリンティングとインポートソート
- すべてのパブリックメソッドに型ヒントが必要
- すべてのクラスとパブリックメソッドにDocstring

#### Gitワークフロー
- フィーチャーブランチ：`feature/domain-feature-name`
- コミットメッセージ：従来のコミットに従う
- すべての変更にプルリクエストが必要
- mainブランチへのスカッシュマージ

#### テスト標準
- すべてのドメインロジックにユニットテスト
- リポジトリとAPIの統合テスト
- 重要なユーザージャーニーのE2Eテスト
- 最小90%のコードカバレッジ

### 3. 実装順序

#### フェーズ 1: 基盤（2週間）
1. プロジェクト構造と依存関係のセットアップ
2. 共有カーネルの実装（ベースエンティティ、イベント、リポジトリ）
3. データベースモデルとマイグレーションのセットアップ
4. 認証と認可の実装
5. FastAPIを使用した基本的なAPI構造

#### フェーズ 2: コアドメイン（4週間）
1. ユーザー管理ドメインとAPI
2. サーバー管理ドメイン（エンティティ、リポジトリ、基本的なCRUD）
3. グループ管理ドメイン
4. 基本的なコマンド/クエリハンドラー

#### フェーズ 3: 高度な機能（4週間）
1. バックグラウンドジョブ処理（サーバー起動/停止）
2. バックアップ管理ドメイン
4. ファイル管理ドメイン
5. イベント駆動アーキテクチャの完成

#### フェーズ 4: リアルタイム＆監視（2週間）
1. WebSocket実装
2. 監視とメトリクス収集  
3. パフォーマンス最適化
4. 包括的なテスト

#### フェーズ 5: 移行＆本番（2週間）
1. V1からのデータ移行スクリプト
2. 本番デプロイメントセットアップ
3. ロードテストと最適化
4. ドキュメントとトレーニング

この技術仕様は、クリーンアーキテクチャの原則に従ってMinecraft Server Dashboard API V2を構築するために必要な詳細な実装パターンとコード例を提供します。