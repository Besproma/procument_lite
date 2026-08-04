"""AG-UI 事件的 Server-Sent Events 编码。"""

from pydantic import BaseModel


def encode_sse_event(event: BaseModel) -> bytes:
    """把一个 Python 事件对象转换成浏览器能接收的一帧 SSE 字节。

    例如 Python 事件最终会变成：

    ``data: {"type":"RUN_FINISHED",...}\n\n``

    SSE 使用两个换行表示“一帧结束”。agent.py 每 yield 一帧，前端就可以立即解析，
    不必等待整个 Graph 全部处理完成。

    JSON 由 Pydantic 统一生成，字符串中的换行会被正确转义，不会突破 SSE frame 边界。
    不设置动态 ``event:`` 名称，客户端直接依据 AG-UI JSON 的 ``type`` 分发。
    """

    # 采购协议把 ``null`` 与字段缺失区分开，例如知识/商品/Scene 的可选展示字段在
    # Zod 契约中明确允许 null。SSE 因此保留 None，不能为省几个字节破坏稳定 Schema。
    json_text = event.model_dump_json(by_alias=True)
    return f"data: {json_text}\n\n".encode()
