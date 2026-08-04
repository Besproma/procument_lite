"""外围 Delegate 复用的异步 HTTP 传输能力。"""

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

from procurement_assistant.domain.errors import (
    DelegateContractError,
    NonRetryableDelegateError,
    RetryableDelegateError,
)


class HttpEndpoint(BaseModel):
    """只能由服务端配置创建的固定外围端点。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: AnyHttpUrl
    headers: dict[str, str] = Field(default_factory=dict)


class SharedHttpClient:
    """连接池、响应大小和传输错误的公共实现。

    本类不知道 IOI、栏目等业务字段，也不解析某家 Agent 的 final_result。每个正式
    Delegate 仍需在自己的文件中把供应方 JSON/流事件映射成内部 Pydantic 模型。URL 只能
    来自 ``HttpEndpoint`` 服务端配置，Graph 用户输入永远不能指定主机，避免 SSRF。
    """

    def __init__(
        self,
        *,
        max_connections: int = 200,
        max_keepalive_connections: int = 50,
        max_response_bytes: int = 10 * 1024 * 1024,
        transport_timeout_seconds: float = 15.0,
    ) -> None:
        self._max_response_bytes = max_response_bytes
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            ),
            # 业务运行时的 asyncio.timeout 才是统一单次上限；HTTPX 仍设置传输层超时，
            # 防止连接建立或连接池等待在调用方取消失效时无限悬挂。
            timeout=httpx.Timeout(transport_timeout_seconds),
            follow_redirects=False,
        )

    async def post_json(
        self,
        endpoint: HttpEndpoint,
        payload: Mapping[str, Any],
    ) -> Any:
        """发送 JSON，并在读取期间限制响应大小。

        不能先调用 ``client.post`` 把整份响应读进内存后再检查长度；恶意或故障外围服务
        可能在限制生效前占满进程内存。这里按字节块累计，超过上限立即关闭响应流。
        """

        try:
            async with self._client.stream(
                "POST",
                str(endpoint.url),
                headers=endpoint.headers,
                json=dict(payload),
            ) as response:
                self._raise_for_status(response)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > self._max_response_bytes:
                        raise DelegateContractError("外围接口响应超过允许大小")
                    content.extend(chunk)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            # ``ReadTimeout``、``ConnectTimeout`` 和 ``PoolTimeout`` 都属于
            # ``TimeoutException``，而连接重置、协议断开等错误属于 ``NetworkError``。
            # 这些错误没有证据表明业务请求本身有问题，交给上层统一重试；不要把
            # ``HTTPStatusError`` 放进这里，否则 4xx 业务拒绝也会被重复发送。
            raise RetryableDelegateError("外围接口网络暂时不可用") from exc
        try:
            return json.loads(content)
        except (UnicodeDecodeError, ValueError) as exc:
            raise DelegateContractError("外围接口没有返回合法 JSON") from exc

    async def stream_lines(
        self,
        endpoint: HttpEndpoint,
        payload: Mapping[str, Any],
    ) -> AsyncIterator[str]:
        """逐行读取流；行的业务含义由具体外围 Delegate 决定。"""

        total_bytes = 0
        try:
            async with self._client.stream(
                "POST",
                str(endpoint.url),
                headers=endpoint.headers,
                json=dict(payload),
            ) as response:
                self._raise_for_status(response)
                async for line in response.aiter_lines():
                    total_bytes += len(line.encode("utf-8"))
                    if total_bytes > self._max_response_bytes:
                        raise DelegateContractError("外围流响应超过允许大小")
                    yield line
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            # 流式响应可能在首段之后断开。上层会按 attempt 记录已经收到的片段，并
            # 依据最终异常决定是否重试；前端只会看到明确允许展示的片段。
            raise RetryableDelegateError("外围流接口网络暂时不可用") from exc

    async def close(self) -> None:
        """应用优雅停止时关闭连接池。"""

        await self._client.aclose()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """把供应方 HTTP 状态映射成稳定、可判断的 Delegate 错误。"""

        if response.status_code < 400:
            return
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise RetryableDelegateError("外围接口暂时不可用")
        # 4xx 多为请求映射、鉴权或业务拒绝；自动重放不会修复问题，必须只调用一次。
        raise NonRetryableDelegateError("外围接口拒绝了请求")
