
# 服务相关异常
from src.typings.errno.error_no import ErrorNo
from .base_exception import BaseAppException

class FileTypeNotSupportedException(BaseAppException):
    """不支持的文件类型"""
    def __init__(self, file_type: str):
        super().__init__(
            message=f"不支持的文件类型: {file_type}",
            code=ErrorNo.FILE_TYPE_NOT_SUPPORTED
        )

class FileParseException(BaseAppException):
    """文件解析失败"""
    def __init__(self, filename: str, reason: str = None):
        super().__init__(
            message=f"文件解析失败: {filename}" + (f" - {reason}" if reason else ""),
            code=ErrorNo.FILE_PARSE_FAILED
        )

class ValidationException(BaseAppException):
    """参数校验失败"""
    def __init__(self, message: str):
        super().__init__(
            message=message,
            code=ErrorNo.VALIDATION_ERROR
        )
