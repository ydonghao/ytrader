"""
错误码定义
统一管理系统所有错误码，参考 Coze Studio 的 errno 模块
"""
from enum import IntEnum
from typing import Dict


class ErrorNo(IntEnum):
    """
    错误码枚举
    错误码分段规则：
    - 0: 成功
    - 1-999: 通用错误
    - 1000-1999: 文件相关错误
    - 2000-2999: 权限相关错误
    - 3000-3999: 业务逻辑错误
    - 4000-4999: 外部服务错误
    - 5000-5999: 系统内部错误
    """

    # 通用
    SUCCESS = 0
    FAIL = 1
    INVALID_PARAM = 100
    VALIDATION_ERROR = 422

    # 服务器错误
    SERVER_ERROR = 500
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504

    # 文件相关 (1000-1999)
    FILE_NOT_FOUND = 1001
    FILE_TYPE_NOT_SUPPORTED = 1002
    FILE_PARSE_FAILED = 1003
    FILE_TOO_LARGE = 1004
    FILE_UPLOAD_FAILED = 1005
    FILE_DOWNLOAD_FAILED = 1006

    # 权限相关 (2000-2999)
    UNAUTHORIZED = 2001
    TOKEN_EXPIRED = 2002
    FORBIDDEN = 2003
    PERMISSION_DENIED = 2004

    # 业务逻辑错误 (3000-3999)
    BUSINESS_RULE_VIOLATION = 3001
    RESOURCE_NOT_FOUND = 3002
    RESOURCE_ALREADY_EXISTS = 3003
    RESOURCE_CONFLICT = 3004
    OPERATION_NOT_ALLOWED = 3005

    # 外部服务错误 (4000-4999)
    EXTERNAL_SERVICE_ERROR = 4001
    EXTERNAL_SERVICE_TIMEOUT = 4002
    EXTERNAL_SERVICE_UNAVAILABLE = 4003

    # 系统内部错误 (5000-5999)
    INTERNAL_ERROR = 5001
    DATABASE_ERROR = 5002
    CACHE_ERROR = 5003
    MESSAGE_QUEUE_ERROR = 5004


# 错误码对应的消息
ERROR_MESSAGES: Dict[ErrorNo, str] = {
    ErrorNo.SUCCESS: "成功",
    ErrorNo.FAIL: "失败",
    ErrorNo.INVALID_PARAM: "参数无效",
    ErrorNo.VALIDATION_ERROR: "数据验证失败",
    ErrorNo.SERVER_ERROR: "服务器内部错误",
    ErrorNo.SERVICE_UNAVAILABLE: "服务不可用",
    ErrorNo.GATEWAY_TIMEOUT: "网关超时",
    ErrorNo.FILE_NOT_FOUND: "文件不存在",
    ErrorNo.FILE_TYPE_NOT_SUPPORTED: "文件类型不支持",
    ErrorNo.FILE_PARSE_FAILED: "文件解析失败",
    ErrorNo.FILE_TOO_LARGE: "文件过大",
    ErrorNo.FILE_UPLOAD_FAILED: "文件上传失败",
    ErrorNo.FILE_DOWNLOAD_FAILED: "文件下载失败",
    ErrorNo.UNAUTHORIZED: "未授权",
    ErrorNo.TOKEN_EXPIRED: "令牌已过期",
    ErrorNo.FORBIDDEN: "禁止访问",
    ErrorNo.PERMISSION_DENIED: "权限不足",
    ErrorNo.BUSINESS_RULE_VIOLATION: "业务规则违反",
    ErrorNo.RESOURCE_NOT_FOUND: "资源不存在",
    ErrorNo.RESOURCE_ALREADY_EXISTS: "资源已存在",
    ErrorNo.RESOURCE_CONFLICT: "资源冲突",
    ErrorNo.OPERATION_NOT_ALLOWED: "操作不允许",
    ErrorNo.EXTERNAL_SERVICE_ERROR: "外部服务错误",
    ErrorNo.EXTERNAL_SERVICE_TIMEOUT: "外部服务超时",
    ErrorNo.EXTERNAL_SERVICE_UNAVAILABLE: "外部服务不可用",
    ErrorNo.INTERNAL_ERROR: "内部错误",
    ErrorNo.DATABASE_ERROR: "数据库错误",
    ErrorNo.CACHE_ERROR: "缓存错误",
    ErrorNo.MESSAGE_QUEUE_ERROR: "消息队列错误",
}


def get_error_message(errno: ErrorNo) -> str:
    """
    获取错误码对应的消息

    Args:
        errno: 错误码

    Returns:
        错误消息
    """
    return ERROR_MESSAGES.get(errno, "未知错误")
