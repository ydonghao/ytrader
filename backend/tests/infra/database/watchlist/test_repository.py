"""自选股仓储测试 — sqlite in-memory，不依赖真实 PG。"""
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

from src.infra.database.watchlist.models import (
    WatchlistGroup,
    WatchlistItem,
)
from src.infra.database.watchlist.repository import WatchlistRepository


class _FakeDb:
    """模拟 DBConnection，session_scope 返回 sqlite session。"""

    def __init__(self, engine):
        self._engine = engine

    @contextmanager
    def session_scope(self):
        # expire_on_commit=False: 与真实 DBConnection.get_session() 保持一致
        # (engine.py), 避免 repository 返回的 ORM 对象在 session 关闭后
        # 被读取属性时抛 DetachedInstanceError。
        with Session(self._engine, expire_on_commit=False) as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise


def _make_repo() -> WatchlistRepository:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(
        engine,
        tables=[WatchlistGroup.__table__, WatchlistItem.__table__],
    )
    return WatchlistRepository(_FakeDb(engine))


# ── 分组 ──

def test_create_and_list_groups_orders_by_sort_index():
    repo = _make_repo()
    g1 = repo.create_group(name="高股息")
    g2 = repo.create_group(name="科技ETF")
    assert g1.sort_index == 0
    assert g2.sort_index == 1
    names = [g.name for g in repo.list_groups()]
    assert names == ["高股息", "科技ETF"]


def test_rename_group():
    repo = _make_repo()
    g = repo.create_group(name="旧名")
    updated = repo.rename_group(g.id, "新名")
    assert updated is not None and updated.name == "新名"
    assert repo.get_group(g.id).name == "新名"


def test_rename_missing_group_returns_none():
    repo = _make_repo()
    assert repo.rename_group(9999, "x") is None


def test_reorder_groups():
    repo = _make_repo()
    a = repo.create_group("A")
    b = repo.create_group("B")
    c = repo.create_group("C")
    repo.reorder_groups([c.id, a.id, b.id])
    ordered = [g.id for g in repo.list_groups()]
    assert ordered == [c.id, a.id, b.id]


def test_count_items_by_group_empty():
    repo = _make_repo()
    assert repo.count_items_by_group() == {}


# ── 成员 ──

def test_add_item_auto_sort_index_and_list_ordered():
    repo = _make_repo()
    g = repo.create_group("G")
    a = repo.add_item(g.id, "sh600519")
    b = repo.add_item(g.id, "sz000001", note="观察")
    assert a.sort_index == 0 and b.sort_index == 1
    items = repo.list_items(g.id)
    assert [it.symbol for it in items] == ["sh600519", "sz000001"]
    assert items[1].note == "观察"


def test_add_item_duplicate_in_same_group_raises():
    from src.infra.database.watchlist.repository import DuplicateWatchlistItem
    repo = _make_repo()
    g = repo.create_group("G")
    repo.add_item(g.id, "sh600519")
    try:
        repo.add_item(g.id, "sh600519")
        assert False, "应抛 DuplicateWatchlistItem"
    except DuplicateWatchlistItem:
        pass


def test_same_symbol_allowed_in_different_groups():
    repo = _make_repo()
    g1 = repo.create_group("G1")
    g2 = repo.create_group("G2")
    repo.add_item(g1.id, "sh600519")
    repo.add_item(g2.id, "sh600519")  # 跨组不报错
    assert len(repo.list_items(g1.id)) == 1
    assert len(repo.list_items(g2.id)) == 1


def test_update_item_note():
    repo = _make_repo()
    g = repo.create_group("G")
    it = repo.add_item(g.id, "sh600519")
    updated = repo.update_item_note(it.id, "等回踩60日线")
    assert updated.note == "等回踩60日线"


def test_delete_item():
    repo = _make_repo()
    g = repo.create_group("G")
    it = repo.add_item(g.id, "sh600519")
    assert repo.delete_item(it.id) is True
    assert repo.get_item(it.id) is None
    assert repo.delete_item(9999) is False


def test_move_item_to_other_group():
    repo = _make_repo()
    g1 = repo.create_group("G1")
    g2 = repo.create_group("G2")
    it = repo.add_item(g1.id, "sh600519")
    moved = repo.move_item(it.id, g2.id)
    assert moved.group_id == g2.id
    assert len(repo.list_items(g1.id)) == 0
    assert len(repo.list_items(g2.id)) == 1


def test_move_item_duplicate_in_target_raises():
    from src.infra.database.watchlist.repository import DuplicateWatchlistItem
    repo = _make_repo()
    g1 = repo.create_group("G1")
    g2 = repo.create_group("G2")
    it = repo.add_item(g1.id, "sh600519")
    repo.add_item(g2.id, "sh600519")
    try:
        repo.move_item(it.id, g2.id)
        assert False, "应抛 DuplicateWatchlistItem"
    except DuplicateWatchlistItem:
        pass


def test_reorder_items():
    repo = _make_repo()
    g = repo.create_group("G")
    a = repo.add_item(g.id, "sh600519")
    b = repo.add_item(g.id, "sz000001")
    c = repo.add_item(g.id, "sh510300")
    repo.reorder_items(g.id, [c.id, a.id, b.id])
    assert [it.id for it in repo.list_items(g.id)] == [c.id, a.id, b.id]


def test_delete_group_cascades_items():
    repo = _make_repo()
    g = repo.create_group("G")
    repo.add_item(g.id, "sh600519")
    repo.add_item(g.id, "sz000001")
    assert repo.delete_group(g.id) is True
    assert repo.get_group(g.id) is None
    assert repo.list_items(g.id) == []
    # count 不应残留
    assert repo.count_items_by_group() == {}


def test_count_items_by_group():
    repo = _make_repo()
    g1 = repo.create_group("G1")
    g2 = repo.create_group("G2")
    repo.add_item(g1.id, "sh600519")
    repo.add_item(g1.id, "sz000001")
    repo.add_item(g2.id, "sh510300")
    assert repo.count_items_by_group() == {g1.id: 2, g2.id: 1}


def test_reorder_items_ignores_foreign_group_ids():
    """排序请求混入其它分组的成员 id 时, 不应改动那个分组的内部顺序。"""
    repo = _make_repo()
    g1 = repo.create_group("G1")
    g2 = repo.create_group("G2")
    a1 = repo.add_item(g1.id, "sh600519")
    a2 = repo.add_item(g1.id, "sz000002")
    b1 = repo.add_item(g2.id, "sz000001")
    b2 = repo.add_item(g2.id, "sh510300")
    # 混入 g1 的 a1 放在末位(位置2): 若无 group_id 守卫, a1 会被改到
    # sort_index=2, g1 顺序翻成 [a2(1), a1(2)]
    repo.reorder_items(g2.id, [b1.id, b2.id, a1.id])
    assert [it.id for it in repo.list_items(g1.id)] == [a1.id, a2.id]
    assert [it.id for it in repo.list_items(g2.id)] == [b1.id, b2.id]
