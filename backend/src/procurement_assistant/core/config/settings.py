"""Core 运行引擎使用的配置对象。

Core 不读取环境变量，也不认识采购业务配置。最外层的 Business 装配代码负责读取
``AppSettings``，再把本文件中的小配置对象传给 Core。这样新增商品字段、外围 Agent
开关或业务缓存时，不需要修改引擎代码。
"""

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class CoreSettings(BaseModel):
    """HTTP 接入、运行治理和生命周期真正需要的通用配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    app_name: str
    cors_allowed_origins: tuple[str, ...] = ()
    run_deadline_seconds: float = Field(gt=0, le=600)
    delegate_attempt_timeout_seconds: float = Field(gt=0, le=120)
    delegate_max_attempts: int = Field(ge=1, le=2)
    thread_lease_grace_seconds: float = Field(ge=5, le=300)
    checkpoint_ttl_hours: int = Field(ge=1, le=168)
    max_concurrent_runs: int = Field(ge=1, le=10_000)
    memory_shutdown_timeout_seconds: float = Field(gt=0, le=60)

    @property
    def thread_lease_seconds(self) -> float:
        """一次会话占用的时长应略大于整个 Run 的最长执行时间。"""

        return self.run_deadline_seconds + self.thread_lease_grace_seconds


class ModelEndpointSettings(BaseModel):
    """一个 OpenAI 兼容模型端点的连接信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: str
    model_name: str
    api_key: SecretStr | None = None


class ModelDelegateSettings(BaseModel):
    """通用模型 Delegate 的主端点和可选备用端点。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    primary: ModelEndpointSettings
    fallback: ModelEndpointSettings | None = None
