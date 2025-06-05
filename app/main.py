from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.core.database import Base, engine
from app.groups.router import router as groups_router
from app.servers.router import router as servers_router

# Import all models to ensure they are registered with SQLAlchemy
from app.users.router import router as users_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DBのテーブルを作成
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
app.include_router(servers_router, prefix="/api/v1/servers", tags=["servers"])
app.include_router(groups_router, prefix="/api/v1/groups", tags=["groups"])
