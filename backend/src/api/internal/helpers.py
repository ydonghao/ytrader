"""
API 内部辅助函数
提供 API 层使用的通用工具函数
"""


def str_to_bool(value: str) -> bool:
    """将字符串转换为布尔值"""
    if isinstance(value, bool):
        return value
    return value.lower() in ('true', '1', 'yes', 'on')
