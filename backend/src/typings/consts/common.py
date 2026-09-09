"""
通用常量定义
定义系统全局使用的常量
"""
from enum import Enum


# 分页相关
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 文件相关
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_FILE_TYPES = ["pdf", "doc", "docx", "txt", "md", "xlsx", "xls", "csv"]

# 时间相关
DEFAULT_TIMEOUT = 30  # 秒
MAX_RETRY_COUNT = 3

# 状态相关
STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"
STATUS_DELETED = "deleted"
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# HTTP 相关
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_FORM = "application/x-www-form-urlencoded"
CONTENT_TYPE_MULTIPART = "multipart/form-data"

# 日志相关
LOG_LEVEL_DEBUG = "DEBUG"
LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_WARNING = "WARNING"
LOG_LEVEL_ERROR = "ERROR"
LOG_LEVEL_CRITICAL = "CRITICAL"


class ServiceType(str, Enum):
    """
    Enum for the different types of services that can be
    registered with the service manager.
    """
    SESSION_SERVICE = 'session_service'
    TASK_SERVICE = 'task_service'
