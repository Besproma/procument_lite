"""多个 Graph 共同使用的少量编排模型。"""

from pydantic import BaseModel, ConfigDict


class RecoverableError(BaseModel):
    """允许用户从最后成功 Checkpoint 重试的安全错误。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    capability: str
    message: str
