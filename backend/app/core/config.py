from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "dev"
    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@db:5432/metabodash"
    REDIS_URL: str = "redis://redis:6379/0"

    S3_ENDPOINT_URL: str = "http://minio:9000"
    S3_BUCKET: str = "metabodash"
    S3_ACCESS_KEY: str = "minioadmin"
    S3_SECRET_KEY: str = "minioadmin"
    S3_REGION: str = "us-east-1"
    S3_PUBLIC_BASE_URL: str = "http://localhost:9000/metabodash"
    LOCAL_STORAGE_DIR: str = "/tmp/metabodash_uploads"
    DATA_DIR: str = "/app/data"

    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None  # e.g. https://api.moonshot.cn/v1 for Kimi
    OPENAI_MODEL_TEXT: str = "moonshot-v1-8k"
    OPENAI_MODEL_VISION: str = "moonshot-v1-8k"
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL_TEXT: str = "gemini-1.5-pro"
    GEMINI_MODEL_VISION: str = "gemini-1.5-pro"
    LLM_TEMPERATURE: float = 1.0  # Kimi K2.5 only allows 1.0

    JWT_SECRET: str = "change_me"
    JWT_EXPIRES_MIN: int = 1440  # Legacy compat
    JWT_ACCESS_EXPIRES_MIN: int = 30
    JWT_REFRESH_EXPIRES_DAYS: int = 7

    # Rate limiting
    LOGIN_RATE_LIMIT_PER_MIN: int = 10

    CORS_ORIGINS: str = "http://localhost:5173,https://servicewechat.com"
    API_BASE_URL: str = "http://localhost:8000"

    # CGM integration
    CGM_PROVIDER_NAME: str = "vendor_cgm"
    CGM_SHARED_SECRET: str | None = None
    CGM_ALLOW_UNSIGNED: bool = True
    CGM_DEVICE_TIMEZONE: str = "Asia/Shanghai"
    CGM_SOURCE_NAME: str = "cgm_device_api"

    # WeChat Mini Program
    WX_APPID: str = ""
    WX_SECRET: str = ""

    # APNs Push Notifications
    APNS_KEY_ID: str = ""
    APNS_TEAM_ID: str = ""
    APNS_BUNDLE_ID: str = "com.xjie.app"
    APNS_KEY_PATH: str = ""  # path to .p8 file
    APNS_USE_SANDBOX: bool = True  # True for dev, False for production

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
