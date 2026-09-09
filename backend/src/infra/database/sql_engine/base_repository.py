"""
基础仓储实现
提供通用的 CRUD 操作
"""
from typing import TypeVar, Generic, Type, Optional, List, Any

from sqlmodel import select

from src.infra.database.database_interface import IBaseRepository
from src.infra.database.sql_engine.engine import DBConnection

T = TypeVar('T')


class BaseRepository(IBaseRepository[T], Generic[T]):
    """
    基础仓储实现
    提供通用的 CRUD 操作
    """

    def __init__(self, db_connection: DBConnection, model: Type[T]):
        self._db = db_connection
        self._model = model

    @property
    def model(self) -> Type[T]:
        return self._model

    def create(self, entity: T) -> T:
        """创建实体"""
        with self._db.session_scope() as session:
            session.add(entity)
            session.refresh(entity)
            return entity

    def get_by_id(self, id: int) -> Optional[T]:
        """根据ID获取实体"""
        with self._db.session_scope() as session:
            statement = select(self._model).where(
                getattr(self._model, 'id') == id
            )
            return session.exec(statement).first()

    def get_all(self) -> List[T]:
        """获取所有实体"""
        with self._db.session_scope() as session:
            statement = select(self._model)
            return list(session.exec(statement).all())

    def update(self, entity: T) -> T:
        """更新实体"""
        with self._db.session_scope() as session:
            session.add(entity)
            session.refresh(entity)
            return entity

    def delete(self, id: int) -> bool:
        """删除实体"""
        with self._db.session_scope() as session:
            statement = select(self._model).where(
                getattr(self._model, 'id') == id
            )
            entity = session.exec(statement).first()
            if entity:
                session.delete(entity)
                return True
            return False

    def count(self) -> int:
        """统计数量"""
        with self._db.session_scope() as session:
            statement = select(self._model)
            return len(list(session.exec(statement).all()))


def create_repository(
    db_connection: DBConnection,
    model: Type[T]
) -> BaseRepository[T]:
    """
    创建基础仓储实例

    Args:
        db_connection: 数据库连接
        model: 数据模型类

    Returns:
        基础仓储实例
    """
    return BaseRepository(db_connection, model)
