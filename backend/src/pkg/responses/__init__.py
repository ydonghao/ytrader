# 统一返回格式
# 遵循 HTTP/JSON 接口事实标准：接口字段使用 camelCase，内部代码使用 snake_case
from dataclasses import dataclass, field
from typing import Any, Generic, List, Optional, TypeVar
from fastapi.responses import JSONResponse
from src.typings.errno.error_no import ErrorNo

# 导入 SSE 相关类
from src.pkg.responses.sse import (
    SseResponse,
    StreamableResponse,
    StreamEvent,
    ChunkData,
)

T = TypeVar("T")


class ResponseCode:
    """响应状态码"""
    SUCCESS = 0
    FAIL = 1
    ERROR = 500


def success(data: Any = None, msg: str = "success") -> JSONResponse:
    """
    成功响应

    Args:
        data: 响应数据
        msg: 成功消息

    Returns:
        JSON 响应

    响应格式：
    {
        "code": 0,
        "msg": "success",
        "data": {...}
    }
    """
    return JSONResponse(
        status_code=200,
        content={
            "code": ErrorNo.SUCCESS.value,
            "msg": msg,
            "data": data
        }
    )


def fail(msg: str = "fail", code: ErrorNo = ErrorNo.FAIL, data: Any = None) -> JSONResponse:
    """
    业务失败响应

    Args:
        msg: 错误消息
        code: 错误码
        data: 响应数据

    Returns:
        JSON 响应

    响应格式：
    {
        "code": 10001,
        "msg": "参数错误",
        "data": null
    }
    """
    return JSONResponse(
        status_code=200,
        content={
            "code": code.value if code else ErrorNo.FAIL.value,
            "msg": msg,
            "data": data
        }
    )


def error(msg: str = "error", code: ErrorNo = ErrorNo.SERVER_ERROR, data: Any = None) -> JSONResponse:
    """
    系统错误响应

    Args:
        msg: 错误消息
        code: 错误码
        data: 响应数据

    Returns:
        JSON 响应
    """
    return JSONResponse(
        status_code=500,
        content={
            "code": code.value if code else ErrorNo.SERVER_ERROR.value,
            "msg": msg,
            "data": data
        }
    )


def validate_error(msg: str = "参数验证失败", errors: Any = None) -> JSONResponse:
    """
    参数验证错误响应

    Args:
        msg: 错误消息
        errors: 验证错误详情

    Returns:
        JSON 响应
    """
    return JSONResponse(
        status_code=422,
        content={
            "code": ErrorNo.INVALID_PARAM.value,
            "msg": msg,
            "data": errors
        }
    )


def unauthorized(msg: str = "未授权", code: ErrorNo = ErrorNo.UNAUTHORIZED) -> JSONResponse:
    """
    未授权响应

    Args:
        msg: 错误消息
        code: 错误码

    Returns:
        JSON 响应
    """
    return JSONResponse(
        status_code=401,
        content={
            "code": code.value,
            "msg": msg,
            "data": None
        }
    )


def forbidden(msg: str = "禁止访问", code: ErrorNo = ErrorNo.FORBIDDEN) -> JSONResponse:
    """
    禁止访问响应

    Args:
        msg: 错误消息
        code: 错误码

    Returns:
        JSON 响应
    """
    return JSONResponse(
        status_code=403,
        content={
            "code": code.value,
            "msg": msg,
            "data": None
        }
    )


def not_found(msg: str = "资源不存在", code: ErrorNo = ErrorNo.RESOURCE_NOT_FOUND) -> JSONResponse:
    """
    资源不存在响应

    Args:
        msg: 错误消息
        code: 错误码

    Returns:
        JSON 响应
    """
    return JSONResponse(
        status_code=404,
        content={
            "code": code.value,
            "msg": msg,
            "data": None
        }
    )


# ======== 分页响应 ========


@dataclass
class PageData(Generic[T]):
    """
    分页数据载体

    包含数据列表和分页元信息，作为响应的 data 字段值。

    Attributes:
        records: 数据列表
        total: 总记录数
        page: 当前页码（从1开始）
        size: 每页大小
        page_size: 总页数（计算属性，snake_case 内部命名）
    """

    records: List[T] = field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 20

    def to_dict(self) -> dict:
        """
        转换为字典，JSON 字段使用 camelCase 以符合 HTTP/JSON 接口标准

        内部代码使用 snake_case，对外输出使用 camelCase
        """
        return {
            "records": self.records,
            "total": self.total,
            "page": self.page,
            "size": self.size,
            "pageSize": self.page_size,  # camelCase for JSON output
        }

    @property
    def page_size(self) -> int:
        """总页数（内部使用 snake_case）"""
        if self.size <= 0:
            return 0
        return (self.total + self.size - 1) // self.size

    @property
    def has_data(self) -> bool:
        """是否有数据"""
        return bool(self.records)

    @property
    def has_next(self) -> bool:
        """是否有下一页"""
        return self.page < self.page_size

    @property
    def has_previous(self) -> bool:
        """是否有上一页"""
        return self.page > 1


@dataclass
class PageResponse(Generic[T]):
    """
    分页响应体

    HTTP 分页接口返回值封装，符合 vue-admin 前端期望的两层嵌套结构。

    响应格式：
    {
        "code": 0,
        "msg": "success",
        "data": {
            "records": [...],
            "total": 100,
            "page": 1,
            "size": 20,
            "pageSize": 5
        }
    }

    Attributes:
        code: 响应码
        msg: 响应消息
        data: 分页数据
    """

    code: int = 0
    msg: str = "success"
    data: Optional[PageData[T]] = None

    @classmethod
    def of(
        cls,
        records: Optional[List[T]],
        total: int,
        size: int = 20,
        page: int = 1,
        msg: str = "success",
    ) -> "PageResponse[T]":
        """
        创建分页响应

        Args:
            records: 数据列表
            total: 总记录数
            size: 每页大小
            page: 当前页码（从1开始）
            msg: 响应消息

        Returns:
            PageResponse 实例
        """
        return cls(
            code=0,
            msg=msg,
            data=PageData(
                records=records or [],
                total=total,
                page=page,
                size=size,
            ),
        )

    @classmethod
    def empty(cls, size: int = 20, page: int = 1) -> "PageResponse[T]":
        """
        创建空的分页响应

        Args:
            size: 每页大小
            page: 当前页码（从1开始）

        Returns:
            空的 PageResponse 实例
        """
        return cls(
            code=0,
            msg="success",
            data=PageData(records=[], total=0, page=page, size=size),
        )

    @classmethod
    def failure(cls, code: int = 1, msg: str = "fail") -> "PageResponse[T]":
        """
        创建失败的空分页响应

        Args:
            code: 错误码
            msg: 错误消息

        Returns:
            失败的 PageResponse 实例
        """
        return cls(
            code=code,
            msg=msg,
            data=None,
        )

    @property
    def is_success(self) -> bool:
        """是否成功"""
        return self.code == 0

    @property
    def is_failure(self) -> bool:
        """是否失败"""
        return self.code != 0

    def to_dict(self) -> dict:
        """转换为字典"""
        result = {
            "code": self.code,
            "msg": self.msg,
        }
        if self.data is not None:
            result["data"] = self.data.to_dict()
        else:
            result["data"] = None
        return result

    def to_json_response(self, status_code: int = 200) -> JSONResponse:
        """转换为 FastAPI JSONResponse"""
        return JSONResponse(
            status_code=status_code,
            content=self.to_dict(),
        )


def page_success(
    records: Optional[List[T]],
    total: int,
    size: int = 20,
    page: int = 1,
    msg: str = "success",
) -> JSONResponse:
    """
    分页成功响应（便捷函数）

    Args:
        records: 数据列表
        total: 总记录数
        size: 每页大小
        page: 当前页码（从1开始）
        msg: 响应消息

    Returns:
        JSON 响应
    """
    response = PageResponse.of(records, total, size, page, msg)
    return response.to_json_response()