from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


# Kimi 官方视觉指南明确列出的图像输入模型。报告 OCR 必须使用这里的显式能力清单；
# 未知或纯文本模型一律失败关闭，避免上传成功后才在异步 worker 中永久重试。
KIMI_IMAGE_CAPABLE_MODELS = frozenset(
    {
        "kimi-k3",
        "moonshot-v1-8k-vision-preview",
        "moonshot-v1-32k-vision-preview",
        "moonshot-v1-128k-vision-preview",
        "kimi-k2.5",
        "kimi-k2.6",
        "kimi-k2.7-code",
        "kimi-k2.7-code-highspeed",
    }
)
OPENAI_IMAGE_CAPABLE_MODELS = frozenset(
    {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
    }
)


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
    # 报告原件是 OCR 的短期输入，单独选择存储后端，不能随饮食图片配置
    # 静默降级。生产默认要求加密 S3；本地仅允许显式 dev/test。
    REPORT_OBJECT_STORAGE_BACKEND: str = "s3"
    LOCAL_STORAGE_DIR: str = "/tmp/metabodash_uploads"
    DATA_DIR: str = "/app/data"
    # Only unconfirmed, workflow-unbound report staging sessions are expired.
    # Attached/confirmed reports are never selected by this retention setting.
    REPORT_UPLOAD_SESSION_TTL_HOURS: int = 72
    REPORT_UPLOAD_CLEANUP_BATCH_SIZE: int = 50

    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str | None = None
    # 默认模型属于 Kimi，因此默认 endpoint 也必须属于同一能力族；密钥仍需显式配置。
    OPENAI_BASE_URL: str | None = "https://api.moonshot.cn/v1"
    OPENAI_MODEL_TEXT: str = "kimi-k2.5"
    OPENAI_MODEL_VISION: str = "kimi-k2.5"
    LLM_TEMPERATURE: float | None = None  # None = use model default; kimi-k2.5 does NOT allow setting temperature

    def validate_report_vision_configuration(
        self,
        *,
        require_credentials: bool = False,
    ) -> None:
        """确认报告 OCR 使用真实支持图片输入的模型。

        Args:
            require_credentials: 为 ``True`` 时同时要求供应商密钥存在，供生产启动检查使用。
        """

        model = self.OPENAI_MODEL_VISION.strip().lower()
        provider_family = self.report_vision_provider_family()
        if provider_family == "moonshot":
            supported = model in KIMI_IMAGE_CAPABLE_MODELS
        else:
            supported = any(
                model == candidate or model.startswith(f"{candidate}-20")
                for candidate in OPENAI_IMAGE_CAPABLE_MODELS
            )
        if not supported:
            raise RuntimeError(
                "OPENAI_MODEL_VISION must be explicitly image-capable for its provider"
            )
        if require_credentials and not self.OPENAI_API_KEY:
            raise RuntimeError("report OCR provider credentials are not configured")

    def report_vision_provider_family(self) -> str:
        """按已审核 endpoint 识别视觉供应商；未知兼容代理不猜测能力。"""

        endpoint = (self.OPENAI_BASE_URL or "").strip()
        if not endpoint:
            return "openai"
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise RuntimeError("report OCR provider endpoint must be a credential-free HTTPS URL")
        if host in {"api.moonshot.cn", "api.moonshot.ai"}:
            return "moonshot"
        if host == "api.openai.com":
            return "openai"
        raise RuntimeError("report OCR provider endpoint is not in the reviewed capability registry")

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
