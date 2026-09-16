import os

base_dir = r'd:\Digitalurth\cinqflow'

files = {
    'backend/requirements.txt': '''fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
alembic==1.13.3
psycopg2-binary==2.9.9
pydantic==2.9.2
pydantic-settings==2.5.2
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
celery==5.4.0
redis==5.1.1
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==5.0.0
factory-boy==3.3.1
dotenv==0.9.1
python-dotenv==1.0.1
aiofiles==24.1.0''',

    'backend/core/config.py': '''from pydantic_settings import BaseSettings
from typing import Literal

class Settings(BaseSettings):
    # App
    APP_NAME: str = "CINQFLOW"
    APP_ENV: Literal["dev", "uat", "prod"] = "dev"
    DEBUG: bool = True
    
    # Database
    DATABASE_URL: str = "postgresql://cinqflow:cinqflow@localhost:5432/cinqflow"
    
    # Auth
    AUTH_PROVIDER: Literal["mock", "entra"] = "mock"
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_MINUTES: int = 480
    
    # Entra (only used when AUTH_PROVIDER=entra)
    ENTRA_TENANT_ID: str = ""
    ENTRA_CLIENT_ID: str = ""
    ENTRA_CLIENT_SECRET: str = ""
    
    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    
    # Storage
    STORAGE_ADAPTER: Literal["local", "azure_blob", "s3"] = "local"
    LOCAL_STORAGE_ROOT: str = "./data"
    LANDING_ZONE_PATH: str = "./data/landing"
    BRONZE_PATH: str = "./data/bronze"
    SILVER_RAW_PATH: str = "./data/silver_raw"
    QUARANTINE_PATH: str = "./data/quarantine"
    
    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"
    
    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()''',

    'backend/core/database.py': '''from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
from backend.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()''',

    'backend/models/base.py': '''import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class AuditMixin:
    """Standard audit columns for every stateful table."""
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)''',

    'backend/main.py': '''from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from backend.core.config import settings
from backend.api import auth, contracts, feeds, inputs, pipeline, quarantine, reconciliation, audit

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown

app = FastAPI(
    title="CINQFLOW API",
    description="Healthcare data platform — Wave 0",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(contracts.router, prefix="/api/v1/contracts", tags=["Contract Register"])
app.include_router(feeds.router, prefix="/api/v1/feeds", tags=["Feed Registry"])
app.include_router(inputs.router, prefix="/api/v1/inputs", tags=["Input Registry"])
app.include_router(pipeline.router, prefix="/api/v1/pipeline", tags=["Pipeline"])
app.include_router(quarantine.router, prefix="/api/v1/quarantine", tags=["Quarantine"])
app.include_router(reconciliation.router, prefix="/api/v1/reconciliation", tags=["Reconciliation"])
app.include_router(audit.router, prefix="/api/v1/audit", tags=["Audit"])

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "env": settings.APP_ENV, "wave": "0"}

@app.get("/api/v1/health", tags=["Health"])
def api_health_check():
    from backend.core.database import engine
    try:
        with engine.connect() as conn:
            conn.execute(__import__('sqlalchemy').text('SELECT 1'))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    return {"status": "ok", "database": db_status, "wave": "0"}''',

    'backend/api/__init__.py': '',

    'backend/api/auth.py': '''from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from backend.core.database import get_db
from backend.schemas.auth import LoginRequest, LoginResponse, UserProfile

router = APIRouter()

@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    from backend.adapters.auth import get_auth_provider
    provider = get_auth_provider()
    result = provider.authenticate(request.credential, db)
    if not result:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return result

@router.post("/logout")
def logout():
    return {"message": "Logged out"}

@router.get("/me", response_model=UserProfile)
def me(db: Session = Depends(get_db)):
    # Will be wired to current_user dependency in Phase 3
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Auth not yet implemented")''',

    'backend/api/contracts.py': '''from fastapi import APIRouter\nrouter = APIRouter()\n# Implemented in Phase 4''',
    'backend/api/feeds.py': '''from fastapi import APIRouter\nrouter = APIRouter()\n# Implemented in Phase 4''',
    'backend/api/inputs.py': '''from fastapi import APIRouter\nrouter = APIRouter()\n# Implemented in Phase 4''',
    'backend/api/pipeline.py': '''from fastapi import APIRouter\nrouter = APIRouter()\n# Implemented in Phase 4''',
    'backend/api/quarantine.py': '''from fastapi import APIRouter\nrouter = APIRouter()\n# Implemented in Phase 4''',
    'backend/api/reconciliation.py': '''from fastapi import APIRouter\nrouter = APIRouter()\n# Implemented in Phase 4''',
    'backend/api/audit.py': '''from fastapi import APIRouter\nrouter = APIRouter()\n# Implemented in Phase 4''',

    'backend/schemas/auth.py': '''from pydantic import BaseModel, EmailStr
from typing import List, Optional
from uuid import UUID

class LoginRequest(BaseModel):
    credential: str  # mock: username, entra: token
    
class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    email: str
    roles: List[str]

class UserProfile(BaseModel):
    id: str
    email: str
    full_name: str
    roles: List[str]
    auth_provider: str''',

    'backend/adapters/auth/base.py': '''from abc import ABC, abstractmethod
from typing import Optional
from sqlalchemy.orm import Session

class AuthProvider(ABC):
    """Interface for authentication providers.
    
    DEV: MockAuthProvider — no external dependencies.
    UAT/PROD: EntraAuthProvider — Microsoft Entra ID.
    """
    
    @abstractmethod
    def authenticate(self, credential: str, db: Session) -> Optional[dict]:
        """Validate credential and return session info, or None if invalid."""
        ...
    
    @abstractmethod
    def get_provider_name(self) -> str:
        ...''',

    'backend/adapters/auth/mock_provider.py': '''from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from jose import jwt
from backend.adapters.auth.base import AuthProvider
from backend.core.config import settings

MOCK_USERS = {
    "engineer": {
        "id": "mock-engineer-001",
        "email": "engineer@cinqflow.local",
        "full_name": "Dev Engineer",
        "roles": ["ENGINEER"],
        "password": "engineer123",
    },
    "readonly": {
        "id": "mock-readonly-001",
        "email": "readonly@cinqflow.local",
        "full_name": "Read Only User",
        "roles": ["READ_ONLY"],
        "password": "readonly123",
    },
}

class MockAuthProvider(AuthProvider):
    """Local development auth provider. No external dependencies.
    Accepts username:password credential.
    Supports ENGINEER and READ_ONLY roles.
    """
    
    def authenticate(self, credential: str, db: Session) -> Optional[dict]:
        # credential format: "username:password"
        try:
            username, password = credential.split(":", 1)
        except ValueError:
            return None
        
        user = MOCK_USERS.get(username)
        if not user or user["password"] != password:
            return None
        
        token_data = {
            "sub": user["id"],
            "email": user["email"],
            "roles": user["roles"],
            "provider": "mock",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRY_MINUTES),
        }
        token = jwt.encode(token_data, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": settings.JWT_EXPIRY_MINUTES * 60,
            "user_id": user["id"],
            "email": user["email"],
            "roles": user["roles"],
        }
    
    def get_provider_name(self) -> str:
        return "mock"''',

    'backend/adapters/auth/entra_provider.py': '''from typing import Optional
from sqlalchemy.orm import Session
from backend.adapters.auth.base import AuthProvider

class EntraAuthProvider(AuthProvider):
    """Microsoft Entra ID authentication provider.
    
    Status: ADAPTER STUB — not connected to production Entra.
    See UNKNOWN_AND_INTEGRATION_REGISTER.md UNK-010.
    Required config: ENTRA_TENANT_ID, ENTRA_CLIENT_ID, ENTRA_CLIENT_SECRET
    """
    
    def authenticate(self, credential: str, db: Session) -> Optional[dict]:
        # TODO: Validate Entra JWT using MSAL
        # TODO: Extract roles from Entra security groups
        raise NotImplementedError(
            "EntraAuthProvider is not yet configured. "
            "Set AUTH_PROVIDER=mock for local development. "
            "See UNK-010 in UNKNOWN_AND_INTEGRATION_REGISTER.md."
        )
    
    def get_provider_name(self) -> str:
        return "entra"''',

    'backend/adapters/auth/__init__.py': '''from backend.core.config import settings
from backend.adapters.auth.base import AuthProvider
from backend.adapters.auth.mock_provider import MockAuthProvider
from backend.adapters.auth.entra_provider import EntraAuthProvider

def get_auth_provider() -> AuthProvider:
    if settings.AUTH_PROVIDER == "mock":
        return MockAuthProvider()
    elif settings.AUTH_PROVIDER == "entra":
        return EntraAuthProvider()
    else:
        raise ValueError(f"Unknown auth provider: {settings.AUTH_PROVIDER}")''',

    'backend/adapters/storage/base.py': '''from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

class StorageAdapter(ABC):
    """Interface for file storage.
    DEV: LocalFilesystemAdapter
    PROD: AzureBlobAdapter or S3Adapter (not yet implemented)
    """
    
    @abstractmethod
    def write_file(self, destination_path: str, content: bytes) -> str:
        """Write bytes to storage. Returns the storage path."""
        ...
    
    @abstractmethod
    def read_file(self, path: str) -> bytes:
        """Read bytes from storage."""
        ...
    
    @abstractmethod
    def file_exists(self, path: str) -> bool:
        ...
    
    @abstractmethod
    def list_files(self, directory: str) -> list[str]:
        ...
    
    @abstractmethod
    def get_adapter_name(self) -> str:
        ...''',

    'backend/adapters/storage/local_adapter.py': '''from pathlib import Path
from backend.adapters.storage.base import StorageAdapter
from backend.core.config import settings

class LocalFilesystemAdapter(StorageAdapter):
    """Local filesystem storage for DEV. All data stored under LOCAL_STORAGE_ROOT."""
    
    def __init__(self):
        Path(settings.LOCAL_STORAGE_ROOT).mkdir(parents=True, exist_ok=True)
        Path(settings.LANDING_ZONE_PATH).mkdir(parents=True, exist_ok=True)
        Path(settings.BRONZE_PATH).mkdir(parents=True, exist_ok=True)
        Path(settings.SILVER_RAW_PATH).mkdir(parents=True, exist_ok=True)
        Path(settings.QUARANTINE_PATH).mkdir(parents=True, exist_ok=True)
    
    def write_file(self, destination_path: str, content: bytes) -> str:
        path = Path(destination_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return str(path)
    
    def read_file(self, path: str) -> bytes:
        return Path(path).read_bytes()
    
    def file_exists(self, path: str) -> bool:
        return Path(path).exists()
    
    def list_files(self, directory: str) -> list[str]:
        p = Path(directory)
        if not p.exists():
            return []
        return [str(f) for f in p.iterdir() if f.is_file()]
    
    def get_adapter_name(self) -> str:
        return "local_filesystem"''',

    'backend/adapters/storage/__init__.py': '''from backend.core.config import settings
from backend.adapters.storage.base import StorageAdapter
from backend.adapters.storage.local_adapter import LocalFilesystemAdapter

def get_storage_adapter() -> StorageAdapter:
    if settings.STORAGE_ADAPTER == "local":
        return LocalFilesystemAdapter()
    else:
        raise NotImplementedError(f"Storage adapter '{settings.STORAGE_ADAPTER}' not yet implemented. See UNKNOWN_AND_INTEGRATION_REGISTER.md")''',

    'database/alembic.ini': '''[alembic]
script_location = database/migrations
file_template = %%(year)d%%(month).2d%%(day).2d_%%(hour).2d%%(minute).2d_%%(rev)s_%%(slug)s
timezone = UTC

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %%H:%%M:%%S''',

    'database/migrations/env.py': '''from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.core.config import settings
from backend.models.base import Base
import backend.models.user
import backend.models.contract
import backend.models.feed
import backend.models.pipeline
import backend.models.input_registry
import backend.models.reconciliation
import backend.models.audit

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()''',

    'database/migrations/script.py.mako': '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}

def upgrade() -> None:
    ${upgrades if upgrades else "pass"}

def downgrade() -> None:
    ${downgrades if downgrades else "pass"}''',

    'docker-compose.yml': '''version: '3.9'

services:
  postgres:
    image: postgres:16-alpine
    container_name: cinqflow_postgres
    environment:
      POSTGRES_USER: cinqflow
      POSTGRES_PASSWORD: cinqflow
      POSTGRES_DB: cinqflow
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cinqflow"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: cinqflow_redis
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

  backend:
    build:
      context: .
      dockerfile: docker/Dockerfile.backend
    container_name: cinqflow_backend
    ports:
      - "8000:8000"
    env_file: .env
    volumes:
      - ./backend:/app/backend
      - ./database:/app/database
      - ./data:/app/data
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

  celery_worker:
    build:
      context: .
      dockerfile: docker/Dockerfile.backend
    container_name: cinqflow_celery
    env_file: .env
    volumes:
      - ./backend:/app/backend
      - ./data:/app/data
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: celery -A backend.workers.pipeline_tasks worker --loglevel=info

  frontend:
    build:
      context: ./frontend
      dockerfile: ../docker/Dockerfile.frontend
    container_name: cinqflow_frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    depends_on:
      - backend

volumes:
  postgres_data:''',

    'docker/Dockerfile.backend': '''FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]''',

    'docker/Dockerfile.frontend': '''FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "start"]''',

    '.env.example': '''# CINQFLOW Wave 0 — Environment Configuration
# Copy to .env and customize

# App
APP_NAME=CINQFLOW
APP_ENV=dev
DEBUG=true

# Database
DATABASE_URL=postgresql://cinqflow:cinqflow@localhost:5432/cinqflow

# Auth — use 'mock' for local dev, 'entra' for UAT/PROD
AUTH_PROVIDER=mock
JWT_SECRET_KEY=dev-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=480

# Entra (only needed when AUTH_PROVIDER=entra)
ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_CLIENT_SECRET=

# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Storage
STORAGE_ADAPTER=local
LOCAL_STORAGE_ROOT=./data
LANDING_ZONE_PATH=./data/landing
BRONZE_PATH=./data/bronze
SILVER_RAW_PATH=./data/silver_raw
QUARANTINE_PATH=./data/quarantine

# Frontend
FRONTEND_URL=http://localhost:3000''',

    '.env': '''# CINQFLOW Wave 0 — Environment Configuration
# Copy to .env and customize

# App
APP_NAME=CINQFLOW
APP_ENV=dev
DEBUG=true

# Database
DATABASE_URL=postgresql://cinqflow:cinqflow@localhost:5432/cinqflow

# Auth — use 'mock' for local dev, 'entra' for UAT/PROD
AUTH_PROVIDER=mock
JWT_SECRET_KEY=dev-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=480

# Entra (only needed when AUTH_PROVIDER=entra)
ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_CLIENT_SECRET=

# Redis
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# Storage
STORAGE_ADAPTER=local
LOCAL_STORAGE_ROOT=./data
LANDING_ZONE_PATH=./data/landing
BRONZE_PATH=./data/bronze
SILVER_RAW_PATH=./data/silver_raw
QUARANTINE_PATH=./data/quarantine

# Frontend
FRONTEND_URL=http://localhost:3000''',

    'frontend/package.json': '''{
  "name": "cinqflow-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "type-check": "tsc --noEmit"
  },
  "dependencies": {
    "next": "14.2.13",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "@tanstack/react-query": "^5.56.2",
    "axios": "^1.7.7",
    "clsx": "^2.1.1",
    "tailwind-merge": "^2.5.2",
    "lucide-react": "^0.441.0",
    "date-fns": "^3.6.0"
  },
  "devDependencies": {
    "typescript": "^5.6.2",
    "@types/node": "^22.5.5",
    "@types/react": "^18.3.6",
    "@types/react-dom": "^18.3.0",
    "tailwindcss": "^3.4.12",
    "autoprefixer": "^10.4.20",
    "postcss": "^8.4.47",
    "eslint": "^8.57.1",
    "eslint-config-next": "14.2.13"
  }
}''',

    'frontend/next.config.ts': '''import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;''',

    'frontend/tsconfig.json': '''{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{"name": "next"}],
    "paths": {"@/*": ["./*"]}
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}''',

    'frontend/tailwind.config.ts': '''import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eff6ff',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          900: '#1e3a8a',
        },
      },
    },
  },
  plugins: [],
};

export default config;''',

    'frontend/postcss.config.js': '''module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};''',

    'frontend/app/layout.tsx': '''import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'CINQFLOW',
  description: 'Healthcare data management platform',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 font-sans antialiased">
        {children}
      </body>
    </html>
  );
}''',

    'frontend/app/globals.css': '''@tailwind base;
@tailwind components;
@tailwind utilities;''',

    'frontend/app/page.tsx': '''import Link from 'next/link';

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <div className="max-w-2xl w-full text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-4">CINQFLOW</h1>
        <p className="text-lg text-gray-600 mb-2">Healthcare Data Management Platform</p>
        <p className="text-sm text-blue-600 font-medium mb-8">Wave 0 — Working Foundation</p>
        <Link
          href="/login"
          className="inline-block bg-blue-600 text-white px-8 py-3 rounded-lg font-medium hover:bg-blue-700 transition-colors"
        >
          Sign In
        </Link>
      </div>
    </main>
  );
}''',

    'frontend/app/login/page.tsx': ''''use client';
import { useState } from 'react';

export default function LoginPage() {
  const [credential, setCredential] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ credential }),
      });
      if (!res.ok) {
        setError('Invalid credentials');
        return;
      }
      const data = await res.json();
      localStorage.setItem('cinqflow_token', data.access_token);
      window.location.href = '/dashboard';
    } catch {
      setError('Connection error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8 bg-gray-50">
      <div className="w-full max-w-md">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">CINQFLOW</h1>
        <p className="text-gray-500 mb-8">Sign in to your account</p>
        <form onSubmit={handleSubmit} className="bg-white p-8 rounded-xl shadow-sm border space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Credential</label>
            <input
              type="text"
              value={credential}
              onChange={e => setCredential(e.target.value)}
              placeholder="engineer:engineer123"
              className="w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              required
            />
            <p className="text-xs text-gray-400 mt-1">Dev: engineer:engineer123 or readonly:readonly123</p>
          </div>
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white py-2 rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
      </div>
    </main>
  );
}''',

    'frontend/lib/api-client.ts': '''const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('cinqflow_token');
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  
  if (res.status === 401) {
    localStorage.removeItem('cinqflow_token');
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }
  
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'API error');
  }
  
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};''',

    'tests/conftest.py': '''import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from backend.main import app
from backend.core.database import get_db
from backend.models.base import Base

TEST_DATABASE_URL = "postgresql://cinqflow:cinqflow@localhost:5432/cinqflow_test"

test_engine = create_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="session", autouse=True)
def create_test_database():
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)

@pytest.fixture
def db():
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()

@pytest.fixture
def client(db):
    def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture
def engineer_token(client):
    res = client.post("/api/v1/auth/login", json={"credential": "engineer:engineer123"})
    assert res.status_code == 200
    return res.json()["access_token"]

@pytest.fixture
def readonly_token(client):
    res = client.post("/api/v1/auth/login", json={"credential": "readonly:readonly123"})
    assert res.status_code == 200
    return res.json()["access_token"]

@pytest.fixture
def engineer_headers(engineer_token):
    return {"Authorization": f"Bearer {engineer_token}"}

@pytest.fixture
def readonly_headers(readonly_token):
    return {"Authorization": f"Bearer {readonly_token}"}''',

    'tests/unit/test_health.py': '''def test_health_endpoint(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["wave"] == "0"

def test_auth_login_engineer(client):
    res = client.post("/api/v1/auth/login", json={"credential": "engineer:engineer123"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert "ENGINEER" in data["roles"]

def test_auth_login_readonly(client):
    res = client.post("/api/v1/auth/login", json={"credential": "readonly:readonly123"})
    assert res.status_code == 200
    data = res.json()
    assert "READ_ONLY" in data["roles"]

def test_auth_login_invalid(client):
    res = client.post("/api/v1/auth/login", json={"credential": "wrong:credentials"})
    assert res.status_code == 401

def test_auth_login_bad_format(client):
    res = client.post("/api/v1/auth/login", json={"credential": "nocodon"})
    assert res.status_code == 401''',

    'tests/fixtures/sample_feed.csv': '''member_id,first_name,last_name,date_of_birth,gender
M001,Alice,Johnson,1985-06-15,F
M002,Bob,Smith,1990-03-22,M
M003,Carol,Williams,1978-11-08,F
M004,INVALID,,2099-01-01,X''',

    'README.md': '''# CINQFLOW — Wave 0: Working Foundation

Healthcare data management platform.

## Quick Start

### Prerequisites
- Docker and Docker Compose
- Python 3.12+ (for local backend dev)
- Node.js 20+ (for local frontend dev)

### Start with Docker
```bash
cd d:\Digitalurth\cinqflow
docker-compose up -d
```

### Local Development (without Docker)

**1. Start dependencies:**
```bash
docker-compose up -d postgres redis
```

**2. Backend:**
```bash
cd d:\Digitalurth\cinqflow
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

**3. Run migrations:**
```bash
alembic -c database/alembic.ini upgrade head
```

**4. Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## Test Credentials (DEV only)
- Engineer: `engineer:engineer123`
- Read-Only: `readonly:readonly123`

## API Health
- http://localhost:8000/health
- http://localhost:8000/api/v1/health
- http://localhost:8000/docs

## Run Tests
```bash
pytest tests/ -v --cov=backend
```

## Wave 0 Scope
Pipeline: Landing → Bronze → Silver Raw → Quarantine → Reconciliation → Audit
No ODS, No Identity Resolution, No AI.
''',

    'backend/workers/pipeline_tasks.py': '''from celery import Celery
from backend.core.config import settings

celery_app = Celery(
    "cinqflow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task(name="pipeline.execute_batch")
def execute_batch(batch_id: str):
    """Execute a pipeline batch. Implemented in Phase 7."""
    # Placeholder — real implementation in Phase 7
    raise NotImplementedError("Pipeline execution implemented in Phase 7")''',
}

empty_init_dirs = [
    'backend/models',
    'backend/schemas',
    'backend/services',
    'backend/engine',
    'backend/engine/stages',
    'backend/workers',
    'backend/adapters',
    'backend/core',
    'tests',
    'tests/unit',
    'tests/integration',
]

empty_files = [
    'backend/models/user.py',
    'backend/models/contract.py',
    'backend/models/feed.py',
    'backend/models/pipeline.py',
    'backend/models/input_registry.py',
    'backend/models/reconciliation.py',
    'backend/models/audit.py',
    'backend/schemas/__init__.py',
    'backend/schemas/contract.py',
    'backend/schemas/feed.py',
    'backend/schemas/pipeline.py',
    'backend/schemas/reconciliation.py',
    'backend/schemas/audit.py',
    'backend/services/__init__.py',
    'backend/services/auth_service.py',
    'backend/services/contract_service.py',
    'backend/services/feed_service.py',
    'backend/services/input_service.py',
    'backend/services/audit_service.py',
    'backend/services/reconciliation_service.py',
    'backend/engine/__init__.py',
    'backend/engine/compiler.py',
    'backend/engine/executor.py',
    'backend/engine/stages/__init__.py',
    'backend/engine/stages/base.py',
    'backend/engine/stages/landing.py',
    'backend/engine/stages/bronze.py',
    'backend/engine/stages/silver_raw.py',
    'backend/workers/__init__.py',
    'tests/__init__.py',
    'tests/unit/__init__.py',
    'tests/integration/__init__.py',
    'database/migrations/versions/.gitkeep',
]

for d in empty_init_dirs:
    os.makedirs(os.path.join(base_dir, d), exist_ok=True)
    with open(os.path.join(base_dir, d, '__init__.py'), 'w', encoding='utf-8') as f:
        pass
        
for ef in empty_files:
    path = os.path.join(base_dir, ef)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        pass

for rel_path, content in files.items():
    path = os.path.join(base_dir, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

print("Files created successfully.")
