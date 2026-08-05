"""FastAPI 请求依赖：当前仅包含临时用户身份头。"""

from typing import Annotated

from fastapi import Header
from pydantic import TypeAdapter, ValidationError

from procurement_assistant.core.domain.errors import InvalidUserInputError
from procurement_assistant.core.domain.identifiers import UserId

_USER_ID_ADAPTER = TypeAdapter(UserId)


async def get_user_id(
    x_user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
) -> str:
    """读取并校验页面直传的 ``X-User-ID``。

    当前按已确认方案不验签，但格式校验和后续每次数据库归属条件仍必须执行。页面区域
    等 forwardedProps 字段绝不能替代身份头。
    """

    if x_user_id is None:
        raise InvalidUserInputError("缺少 X-User-ID 请求头")
    try:
        return _USER_ID_ADAPTER.validate_python(x_user_id)
    except ValidationError as exc:
        raise InvalidUserInputError("X-User-ID 格式不合法") from exc
