"""
错误码测试
遵循 AAA (Arrange-Act-Assert) 测试规范
"""
import pytest

from src.typings.errno.error_no import ErrorNo, ERROR_MESSAGES, get_error_message


class TestErrorNo:
    """ErrorNo 枚举测试"""

    def test_success_should_be_zero(self):
        """成功错误码应该为 0"""
        # arrange - no setup needed

        # act
        result = ErrorNo.SUCCESS.value

        # assert
        assert result == 0

    def test_file_not_found_should_be_in_1000_range(self):
        """文件不存在错误码应该在 1000-1999 范围内"""
        # arrange
        file_errors = [
            ErrorNo.FILE_NOT_FOUND,
            ErrorNo.FILE_TYPE_NOT_SUPPORTED,
            ErrorNo.FILE_PARSE_FAILED,
            ErrorNo.FILE_TOO_LARGE,
        ]

        # act & assert
        for error in file_errors:
            assert 1000 <= error.value < 2000, f"{error.name} should be in 1000-1999 range"

    def test_auth_errors_should_be_in_2000_range(self):
        """权限错误码应该在 2000-2999 范围内"""
        # arrange
        auth_errors = [
            ErrorNo.UNAUTHORIZED,
            ErrorNo.TOKEN_EXPIRED,
            ErrorNo.FORBIDDEN,
            ErrorNo.PERMISSION_DENIED,
        ]

        # act & assert
        for error in auth_errors:
            assert 2000 <= error.value < 3000, f"{error.name} should be in 2000-2999 range"


class TestGetErrorMessage:
    """get_error_message 函数测试"""

    def test_should_return_success_message(self):
        """应该返回成功消息"""
        # arrange
        errno = ErrorNo.SUCCESS

        # act
        result = get_error_message(errno)

        # assert
        assert result == "成功"

    def test_should_return_file_not_found_message(self):
        """应该返回文件不存在消息"""
        # arrange
        errno = ErrorNo.FILE_NOT_FOUND

        # act
        result = get_error_message(errno)

        # assert
        assert result == "文件不存在"

    def test_all_errors_should_have_messages(self):
        """所有错误码都应该有对应的消息"""
        # arrange
        all_errors = list(ErrorNo)

        # act & assert
        for error in all_errors:
            message = get_error_message(error)
            assert message is not None, f"{error.name} should have a message"
            assert message != "未知错误", f"{error.name} should not return unknown error"
