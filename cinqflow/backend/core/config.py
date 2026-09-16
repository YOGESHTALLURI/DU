from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal

class Settings(BaseSettings):
    # App
    APP_NAME: str = "CINQFLOW"
    APP_ENV: Literal["dev", "uat", "prod"] = "dev"
    DEBUG: bool = True
    SQL_ECHO: bool = False
    
    # Database
    DATABASE_URL: str = "postgresql+psycopg://cinqflow:cinqflow@localhost:5432/cinqflow"
    TEST_DATABASE_URL: str = "postgresql+psycopg://cinqflow:cinqflow@localhost:5432/cinqflow_test"
    
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
    SAMPLE_PATH: str = "./data/samples"
    # Frontend
    FRONTEND_URL: str = "http://localhost:3000"

    # Identity / Privacy
    IDENTITY_HASH_PEPPER: str = "cinqflow-dev-identity-pepper-2026"
    IDENTITY_HASH_PEPPER_V1: str = "TEST_PEPPER_KEY_V1"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()