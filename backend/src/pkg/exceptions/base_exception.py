
# 基础异常
from typing import Dict, Optional
from src.typings.errno.error_no import ErrorNo


class BaseAppException(Exception):
    """
    应用程序基础异常类
    """
    def __init__(self,
                 message: str,
                 code: ErrorNo = ErrorNo.SERVER_ERROR,
                 detail: Optional[Dict] = None):
        self.message = message
        self.code = code
        self.detail = detail or {}
        super().__init__(message)

    def to_dict(self):
        return {
            "code": self.code.value,  # 枚举转数字
            "msg": self.message,
            "detail": self.detail
        }
