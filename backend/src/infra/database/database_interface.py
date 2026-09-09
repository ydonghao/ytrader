"""
数据库接口
定义数据库连接和会话管理的标准接口
"""
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Type, Optional, List, Any, Tuple
from contextlib import contextmanager

T = TypeVar('T')


class IDatabaseSession(ABC):
    """
    数据库会话接口
    """

    @abstractmethod
    def add(self, entity: Any) -> None:
        """添加实体"""
        pass

    @abstractmethod
    def delete(self, entity: Any) -> None:
        """删除实体"""
        pass

    @abstractmethod
    def commit(self) -> None:
        """提交事务"""
        pass

    @abstractmethod
    def rollback(self) -> None:
        """回滚事务"""
        pass

    @abstractmethod
    def refresh(self, entity: Any) -> None:
        """刷新实体"""
        pass

    @abstractmethod
    def query(self, model: Type[T]) -> Any:
        """创建查询"""
        pass

    @abstractmethod
    def close(self) -> None:
        """关闭会话"""
        pass


class IDatabaseConnection(ABC):
    """
    数据库连接接口
    """

    @abstractmethod
    def get_session(self) -> IDatabaseSession:
        """获取数据库会话"""
        pass

    @abstractmethod
    @contextmanager
    def session_scope(self):
        """
        会话上下文管理器
        自动处理提交和回滚
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """关闭连接"""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查"""
        pass


class IBaseRepository(ABC, Generic[T]):
    """
    基础仓储接口
    提供通用的 CRUD 操作
    """

    @abstractmethod
    def create(self, entity: T) -> T:
        """创建实体"""
        pass

    @abstractmethod
    def get_by_id(self, id: int) -> Optional[T]:
        """根据ID获取实体"""
        pass

    @abstractmethod
    def get_all(self) -> List[T]:
        """获取所有实体"""
        pass

    @abstractmethod
    def update(self, entity: T) -> T:
        """更新实体"""
        pass

    @abstractmethod
    def delete(self, id: int) -> bool:
        """删除实体"""
        pass

    @abstractmethod
    def count(self) -> int:
        """统计数量"""
        pass
