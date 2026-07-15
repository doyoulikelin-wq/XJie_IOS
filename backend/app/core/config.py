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
    S3_SERVER_SIDE_ENCRYPTION: str = "AES256"
    S3_SSE_KMS_KEY_ID: str = ""
    # Persistent retry originals use shared S3-compatible object storage by
    # default.  A local filesystem backend is accepted only when APP_ENV is an
    # explicit development/test environment (see object_storage.py).
    DIETARY_IMAGE_STORAGE_BACKEND: str = "s3"
    LOCAL_STORAGE_DIR: str = "/tmp/metabodash_uploads"
    DATA_DIR: str = "/app/data"

    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None  # e.g. https://api.moonshot.cn/v1 for Kimi
    OPENAI_MODEL_TEXT: str = "kimi-k2.5"
    OPENAI_MODEL_VISION: str = "kimi-k2.5"
    LLM_TEMPERATURE: float | None = None  # None = use model default; kimi-k2.5 does NOT allow setting temperature

    def llm_temperature_kwargs(self, model: str | None = None) -> dict:
        """Return {'temperature': x} or {} depending on model.

        kimi-k2.5 does not allow temperature to be set at all.
        moonshot-v1-* defaults to 0.0, kimi-k2 defaults to 0.6.
        """
        m = (model or self.OPENAI_MODEL_TEXT).lower()
        if m.startswith("kimi-k2.5"):
            return {}  # kimi-k2.5: temperature is not configurable
        if self.LLM_TEMPERATURE is not None:
            return {"temperature": self.LLM_TEMPERATURE}
        return {}

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
