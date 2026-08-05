"""应用配置。

所有环境变量只允许在本模块读取。业务节点和 Delegate 不能自行调用 ``os.getenv``，
否则同一个配置会散落在多个文件中，既难以理解，也无法在启动时一次性发现错误。
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from procurement_assistant.core.config.settings import (
    CoreSettings,
    ModelDelegateSettings,
    ModelEndpointSettings,
)


class AppEnvironment(StrEnum):
    """应用运行模式。

    ``local`` 和 ``test`` 可以由测试 Composition Root 装配 Fake；``production`` 必须
    装配真实 Delegate，不能通过一个运行时开关静默降级成 Fake。
    """

    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class AppSettings(BaseSettings):
    """采购智能助手的全部后端配置。

    字段默认值只用于已经确认的架构决策。URL、凭据和正式业务协议没有默认值，避免
    开发环境中的占位地址意外进入生产环境。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: AppEnvironment = AppEnvironment.LOCAL
    app_name: str = "采购智能助手轻量版"

    database_dsn: SecretStr | None = None
    db_pool_min_size: int = Field(default=2, ge=1, le=100)
    db_pool_max_size: int = Field(default=20, ge=1, le=500)
    http_max_connections: int = Field(default=500, ge=1, le=5000)
    http_max_keepalive_connections: int = Field(default=100, ge=1, le=1000)
    http_max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)

    run_deadline_seconds: float = Field(default=100.0, gt=0, le=600)
    delegate_attempt_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    delegate_max_attempts: int = Field(default=2, ge=1, le=2)
    thread_lease_grace_seconds: float = Field(default=30.0, ge=5, le=300)
    checkpoint_ttl_hours: int = Field(default=24, ge=1, le=168)
    knowledge_cache_ttl_seconds: int = Field(default=600, ge=1, le=86_400)
    product_page_size: int = Field(default=3, ge=1, le=20)
    max_concurrent_runs: int = Field(default=200, ge=1, le=10_000)
    memory_shutdown_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    # 每个外围 Agent 单独决定是否把经过白名单过滤的流片段发送给前端。默认全部关闭，
    # 只有接口所有方明确确认可展示字段后才在部署配置中开启。
    ioi_expose_stream_to_ui: bool = False
    column_expose_stream_to_ui: bool = False
    duplicate_self_purchase_expose_stream_to_ui: bool = False

    procurement_hotline_text: str | None = None

    model_base_url: str | None = None
    model_api_key: SecretStr | None = None
    model_name: str | None = None
    fallback_model_base_url: str | None = None
    fallback_model_api_key: SecretStr | None = None
    fallback_model_name: str | None = None

    cors_allowed_origins: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_related_settings(self) -> "AppSettings":
        """检查多个字段之间的约束。

        Pydantic 的单字段范围检查无法发现“最小连接数大于最大连接数”这类组合错误，
        因此在启动阶段集中验证。错误必须在应用接流量前出现，不能等到首个用户请求。
        """

        if self.db_pool_min_size > self.db_pool_max_size:
            raise ValueError("DB_POOL_MIN_SIZE 不能大于 DB_POOL_MAX_SIZE")
        if self.http_max_keepalive_connections > self.http_max_connections:
            raise ValueError("HTTP_MAX_KEEPALIVE_CONNECTIONS 不能大于 HTTP_MAX_CONNECTIONS")

        fallback_values = (
            self.fallback_model_base_url,
            self.fallback_model_api_key,
            self.fallback_model_name,
        )
        if any(value is not None for value in fallback_values) and not all(
            value is not None for value in fallback_values
        ):
            raise ValueError("备用模型必须同时配置 base_url、api_key 和 model_name")

        if self.app_env == AppEnvironment.PRODUCTION:
            required_values = {
                "DATABASE_DSN": self.database_dsn,
                "MODEL_BASE_URL": self.model_base_url,
                "MODEL_NAME": self.model_name,
                "PROCUREMENT_HOTLINE_TEXT": self.procurement_hotline_text,
            }
            missing = [name for name, value in required_values.items() if value is None]
            if missing:
                raise ValueError(f"production 缺少必需配置：{', '.join(missing)}")
            if not self.cors_allowed_origins:
                raise ValueError("production 必须显式配置 CORS_ALLOWED_ORIGINS")

        return self

    def to_core_settings(self) -> CoreSettings:
        """只把引擎需要的配置交给 Core。

        显式逐字段映射看起来比直接传 ``self`` 多几行，但边界非常清楚：以后即使
        ``AppSettings`` 新增一百个采购业务字段，Core 仍只能看到这里列出的字段。
        """

        return CoreSettings(
            app_name=self.app_name,
            cors_allowed_origins=tuple(self.cors_allowed_origins),
            run_deadline_seconds=self.run_deadline_seconds,
            delegate_attempt_timeout_seconds=self.delegate_attempt_timeout_seconds,
            delegate_max_attempts=self.delegate_max_attempts,
            thread_lease_grace_seconds=self.thread_lease_grace_seconds,
            checkpoint_ttl_hours=self.checkpoint_ttl_hours,
            max_concurrent_runs=self.max_concurrent_runs,
            memory_shutdown_timeout_seconds=self.memory_shutdown_timeout_seconds,
        )

    def to_business_settings(self) -> "BusinessSettings":
        """提取业务节点和业务缓存真正需要的配置。"""

        return BusinessSettings(
            knowledge_cache_ttl_seconds=self.knowledge_cache_ttl_seconds,
            product_page_size=self.product_page_size,
            ioi_expose_stream_to_ui=self.ioi_expose_stream_to_ui,
            column_expose_stream_to_ui=self.column_expose_stream_to_ui,
            duplicate_self_purchase_expose_stream_to_ui=(
                self.duplicate_self_purchase_expose_stream_to_ui
            ),
            procurement_hotline_text=self.procurement_hotline_text,
        )

    def to_model_settings(self) -> ModelDelegateSettings:
        """把环境变量中的模型连接信息转换为 Core 通用模型配置。"""

        if self.model_base_url is None or self.model_name is None:
            raise ValueError("OpenAI 兼容模型缺少 MODEL_BASE_URL 或 MODEL_NAME")
        primary = ModelEndpointSettings(
            base_url=self.model_base_url,
            model_name=self.model_name,
            api_key=self.model_api_key,
        )
        fallback: ModelEndpointSettings | None = None
        if self.fallback_model_base_url is not None and self.fallback_model_name is not None:
            fallback = ModelEndpointSettings(
                base_url=self.fallback_model_base_url,
                model_name=self.fallback_model_name,
                api_key=self.fallback_model_api_key,
            )
        return ModelDelegateSettings(primary=primary, fallback=fallback)


class BusinessSettings(BaseModel):
    """采购业务节点使用的配置，不包含 HTTP、数据库和模型连接信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    knowledge_cache_ttl_seconds: int = Field(ge=1, le=86_400)
    product_page_size: int = Field(ge=1, le=20)
    ioi_expose_stream_to_ui: bool
    column_expose_stream_to_ui: bool
    duplicate_self_purchase_expose_stream_to_ui: bool
    procurement_hotline_text: str | None = None
