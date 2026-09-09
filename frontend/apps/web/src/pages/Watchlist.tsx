import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {getApiBase} from '../lib/api';
import {useIntervalWhenVisible} from '../hooks/useIntervalWhenVisible';
import {StockSelect} from '../components/MarketPage/StockSelect';
import {
  Button,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  ModalTitle,
  Tabs,
  Tab,
  TabList,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableHeaderCell,
  TableCell,
} from '@ytrader/common-components';
import {PageHeader, StateView} from '../components/ui';
import './Watchlist.css';

const API_BASE = getApiBase();

interface Group {
  id: number;
  name: string;
  sort_index: number;
  item_count: number;
}
interface Item {
  id: number;
  group_id: number;
  symbol: string;
  note: string | null;
  sort_index: number;
}
interface Quote {
  symbol: string;
  name: string;
  price: number;
  change: number | null;
  change_pct: number | null;
  pe: number | null;
  pe_ttm: number | null;
  pb: number | null;
  dv_ratio: number | null;
  dv_ttm: number | null;
  total_mv: number | null;
}

const nf = (v: number | null | undefined, d = 2) =>
  v == null || Number.isNaN(v) ? '—' : v.toFixed(d);
const fmtMv = (v: number | null) => {
  if (v == null) return '—';
  if (v >= 1e12) return (v / 1e12).toFixed(2) + '万亿';
  return (v / 1e8).toFixed(2) + '亿';
};

// ── fetch helpers ({code,msg,data}, code===0 成功) ──
const jget = (u: string) => fetch(u).then((r) => r.json());
const jpost = (u: string, b?: unknown) =>
  fetch(u, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: b ? JSON.stringify(b) : undefined,
  }).then((r) => r.json());
const jput = (u: string, b: unknown) =>
  fetch(u, {
    method: 'PUT',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(b),
  }).then((r) => r.json());
const jdel = (u: string) => fetch(u, {method: 'DELETE'}).then((r) => r.json());

export const Watchlist: React.FC = () => {
  const [groups, setGroups] = useState<Group[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  // 分组管理弹窗
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [renaming, setRenaming] = useState<Group | null>(null);
  const [renameVal, setRenameVal] = useState('');
  const [deleting, setDeleting] = useState<Group | null>(null);

  const fetchGroups = useCallback(async () => {
    setLoading(true);
    try {
      const j = await jget(`${API_BASE}/watchlist/groups`);
      const list: Group[] = j.code === 0 ? j.data || [] : [];
      setGroups(list);
      setActiveId((cur) => {
        if (cur != null && list.some((g) => g.id === cur)) return cur;
        return list.length ? list[0].id : null;
      });
      setErr(j.code === 0 ? null : j.msg || '加载分组失败');
    } catch (e) {
      setErr('加载分组失败：' + e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  const activeGroup = groups.find((g) => g.id === activeId) || null;

  const [items, setItems] = useState<Item[]>([]);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [itemsLoading, setItemsLoading] = useState(false);

  // 添加股票
  const [addSym, setAddSym] = useState('');
  const [addNote, setAddNote] = useState('');
  // 备注 inline 编辑
  const [editNoteId, setEditNoteId] = useState<number | null>(null);
  const [editNoteVal, setEditNoteVal] = useState('');
  // 跨组移动
  const [movingItem, setMovingItem] = useState<Item | null>(null);
  // 拖拽排序
  const dragId = useRef<number | null>(null);
  // 分组 Tab 拖拽排序
  const dragGroupId = useRef<number | null>(null);

  const fetchQuotes = useCallback(async (syms: string[]) => {
    if (!syms.length) {
      setQuotes({});
      return;
    }
    try {
      const j = await jpost(`${API_BASE}/market/quotes`, {symbols: syms});
      if (j.code === 0) {
        const m: Record<string, Quote> = {};
        for (const q of j.data || []) m[q.symbol] = q;
        setQuotes(m);
      }
    } catch {
      /* 轮询失败静默, 保留上次数据 */
    }
  }, []);

  const fetchItems = useCallback(
    async (gid: number) => {
      setItemsLoading(true);
      try {
        const j = await jget(`${API_BASE}/watchlist/groups/${gid}/items`);
        const list: Item[] = j.code === 0 ? j.data || [] : [];
        setItems(list);
        await fetchQuotes(list.map((it) => it.symbol));
      } finally {
        setItemsLoading(false);
      }
    },
    [fetchQuotes],
  );

  // 切组时拉成员 + 报价
  useEffect(() => {
    setItems([]);
    setQuotes({});
    if (activeId != null) fetchItems(activeId);
  }, [activeId, fetchItems]);

  // 30s 轮询当前组报价（仅当前组）；页面隐藏时暂停
  useIntervalWhenVisible(
    () => fetchQuotes(items.map((it) => it.symbol)),
    activeId == null ? null : 30000,
  );

  const handleAdd = async () => {
    const symbol = addSym.trim();
    if (!symbol || activeId == null) return;
    try {
      const j = await jpost(`${API_BASE}/watchlist/groups/${activeId}/items`, {
        symbol,
        note: addNote.trim() || undefined,
      });
      if (j.code === 0) {
        setAddSym('');
        setAddNote('');
        await Promise.all([fetchItems(activeId), fetchGroups()]); // 刷新列表 + Tab 上的 item_count
      } else {
        alert(j.msg || '添加失败');
      }
    } catch (e) {
      alert('操作失败：' + e);
    }
  };

  const handleRemove = async (it: Item) => {
    if (activeId == null) return;
    try {
      const j = await jdel(`${API_BASE}/watchlist/items/${it.id}`);
      if (j.code === 0) {
        await Promise.all([fetchItems(activeId), fetchGroups()]);
      } else {
        alert(j.msg || '删除失败');
      }
    } catch (e) {
      alert('操作失败：' + e);
    }
  };

  const saveNote = async (it: Item) => {
    try {
      const j = await jput(`${API_BASE}/watchlist/items/${it.id}`, {
        note: editNoteVal.trim(),
      });
      if (j.code === 0) {
        setItems((prev) =>
          prev.map((x) =>
            x.id === it.id ? {...x, note: editNoteVal.trim() || null} : x,
          ),
        );
        setEditNoteId(null);
      } else {
        alert(j.msg || '保存失败');
      }
    } catch (e) {
      alert('操作失败：' + e);
    }
  };

  const handleMove = async (toGroupId: number) => {
    if (!movingItem) return;
    try {
      const j = await jpost(`${API_BASE}/watchlist/items/move`, {
        item_id: movingItem.id,
        to_group_id: toGroupId,
      });
      setMovingItem(null);
      if (j.code === 0) {
        if (activeId != null) await fetchItems(activeId);
        await fetchGroups();
      } else {
        alert(j.msg || '移动失败');
      }
    } catch (e) {
      alert('操作失败：' + e);
    }
  };

  // 拖拽排序：原生 HTML5 DnD
  const onDragStart = (id: number) => () => {
    dragId.current = id;
  };
  const onDrop = (targetId: number) => () => {
    const src = dragId.current;
    dragId.current = null;
    if (src == null || src === targetId || activeId == null) return;
    const ordered = items.map((it) => it.id);
    const from = ordered.indexOf(src);
    const to = ordered.indexOf(targetId);
    if (from < 0 || to < 0) return;
    ordered.splice(from, 1);
    ordered.splice(to, 0, src);
    // 乐观更新
    const byId = new Map(items.map((it) => [it.id, it]));
    setItems(ordered.map((id) => byId.get(id)!));
    jput(`${API_BASE}/watchlist/groups/${activeId}/items/order`, {ids: ordered});
  };

  // 分组 Tab 拖拽排序(原生 HTML5 DnD, 与成员行同一模式)
  const onGroupDragStart = (id: number) => () => {
    dragGroupId.current = id;
  };
  const onGroupDrop = (targetId: number) => () => {
    const src = dragGroupId.current;
    dragGroupId.current = null;
    if (src == null || src === targetId) return;
    const ordered = groups.map((g) => g.id);
    const from = ordered.indexOf(src);
    const to = ordered.indexOf(targetId);
    if (from < 0 || to < 0) return;
    ordered.splice(from, 1);
    ordered.splice(to, 0, src);
    // 乐观更新
    const byId = new Map(groups.map((g) => [g.id, g]));
    setGroups(ordered.map((id) => byId.get(id)!));
    jput(`${API_BASE}/watchlist/groups/order`, {ids: ordered});
  };

  // 概览条统计
  const summary = useMemo(() => {
    const vals = items
      .map((it) => quotes[it.symbol]?.change_pct)
      .filter((v): v is number => v != null);
    const up = vals.filter((v) => v > 0).length;
    const down = vals.filter((v) => v < 0).length;
    const flat = vals.length - up - down;
    const avg = vals.length
      ? vals.reduce((a, b) => a + b, 0) / vals.length
      : null;
    const totalMv = items.reduce(
      (s, it) => s + (quotes[it.symbol]?.total_mv || 0),
      0,
    );
    return {avg, up, down, flat, has: vals.length > 0, totalMv};
  }, [items, quotes]);

  const otherGroups = groups.filter((g) => g.id !== movingItem?.group_id);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    const j = await jpost(`${API_BASE}/watchlist/groups`, {name});
    if (j.code === 0) {
      setCreating(false);
      setNewName('');
      await fetchGroups();
      setActiveId(j.data.id);
    } else {
      alert(j.msg || '创建失败');
    }
  };

  const handleRename = async () => {
    if (!renaming) return;
    const name = renameVal.trim();
    if (!name) return;
    const j = await jput(`${API_BASE}/watchlist/groups/${renaming.id}`, {name});
    if (j.code === 0) {
      setRenaming(null);
      await fetchGroups();
    } else {
      alert(j.msg || '改名失败');
    }
  };

  const handleDelete = async () => {
    if (!deleting) return;
    const j = await jdel(`${API_BASE}/watchlist/groups/${deleting.id}`);
    if (j.code === 0) {
      setDeleting(null);
      await fetchGroups();
    } else {
      alert(j.msg || '删除失败');
    }
  };

  return (
    <div className="watchlist">
      <PageHeader title="自选股" />

      {/* 分组 Tabs + 操作 */}
      <div className="watchlist__tabs">
        {groups.length === 0 && !loading ? (
          <span className="watchlist__tabs-empty">还没有分组，点「+ 新建分组」</span>
        ) : (
          <Tabs
            value={activeId != null ? String(activeId) : undefined}
            onChange={(v) => setActiveId(Number(v))}
          >
            <TabList>
              {groups.map((g) => (
                <Tab
                  key={g.id}
                  value={String(g.id)}
                  className="watchlist__tab-drag"
                  draggable
                  onDragStart={onGroupDragStart(g.id)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={onGroupDrop(g.id)}
                  title="点击切换 / 拖拽排序">
                  {g.name} <span className="watchlist__count">({g.item_count})</span>
                </Tab>
              ))}
            </TabList>
          </Tabs>
        )}
        <div className="watchlist__tabs-actions">
          <Button size="sm" variant="ghost" onClick={() => setCreating(true)}>
            + 新建分组
          </Button>
          {activeGroup && (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setRenaming(activeGroup);
                  setRenameVal(activeGroup.name);
                }}
              >
                改名
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setDeleting(activeGroup)}
              >
                删除
              </Button>
            </>
          )}
        </div>
      </div>

      {err && <div className="watchlist__error">{err}</div>}

      {activeGroup && (
        <>
          {/* 分组概览条 */}
          <div className="watchlist__summary">
            <span className="watchlist__summary-item">
              平均涨幅{' '}
              <b
                className={
                  summary.avg == null
                    ? 'num'
                    : summary.avg > 0
                      ? 'num is-up'
                      : summary.avg < 0
                        ? 'num is-down'
                        : 'num'
                }>
                {summary.avg == null ? '—' : (summary.avg > 0 ? '+' : '') + summary.avg.toFixed(2) + '%'}
              </b>
            </span>
            <span className="watchlist__summary-item">
              涨 <b className="num is-up">{summary.up}</b> / 跌{' '}
              <b className="num is-down">{summary.down}</b> / 平 {summary.flat}
            </span>
            <span className="watchlist__summary-item">
              总市值 <b className="num">{fmtMv(summary.has ? summary.totalMv : null)}</b>
            </span>
          </div>

          {/* 添加股票 */}
          <div className="watchlist__addbar">
            <div className="watchlist__addbar-select">
              <StockSelect value={addSym} onChange={setAddSym} market="A" />
            </div>
            <Input
              value={addNote}
              onChange={(e) => setAddNote(e.target.value)}
              placeholder="备注(可选)"
            />
            <Button variant="primary" onClick={handleAdd}>
              加入
            </Button>
          </div>

          {/* 成员表 */}
          {items.length === 0 ? (
            itemsLoading ? (
              <StateView state="loading" />
            ) : (
              <StateView state="empty" text="该分组还没有股票，用上方搜索框添加。" />
            )
          ) : (
            <Table variant="striped" className="watchlist__table">
              <TableHead>
                <TableRow>
                  <TableHeaderCell>⠿</TableHeaderCell>
                  <TableHeaderCell>名称 / 代码</TableHeaderCell>
                  <TableHeaderCell numeric>现价</TableHeaderCell>
                  <TableHeaderCell numeric>涨跌额</TableHeaderCell>
                  <TableHeaderCell numeric>涨跌幅</TableHeaderCell>
                  <TableHeaderCell numeric>PE</TableHeaderCell>
                  <TableHeaderCell numeric>PB</TableHeaderCell>
                  <TableHeaderCell numeric>股息率</TableHeaderCell>
                  <TableHeaderCell numeric>总市值</TableHeaderCell>
                  <TableHeaderCell>备注</TableHeaderCell>
                  <TableHeaderCell>操作</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((it) => {
                  const q = quotes[it.symbol];
                  return (
                    <TableRow
                      key={it.id}
                      draggable
                      onDragStart={onDragStart(it.id)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={onDrop(it.id)}
                      className="watchlist__row">
                      <TableCell>
                        <span className="watchlist__drag" title="拖拽排序">
                          ⠿
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className="watchlist__sym">
                          <span className="watchlist__sym-name">
                            {q?.name || it.symbol}
                          </span>
                          <span className="watchlist__sym-code">{it.symbol}</span>
                        </div>
                      </TableCell>
                      <TableCell numeric>{nf(q?.price)}</TableCell>
                      <TableCell numeric>{nf(q?.change)}</TableCell>
                      <TableCell numeric>
                        {q && q.change_pct != null ? (
                          <span
                            className={
                              q.change_pct > 0
                                ? 'num is-up'
                                : q.change_pct < 0
                                  ? 'num is-down'
                                  : 'num'
                            }>
                            {(q.change_pct > 0 ? '+' : '') +
                              q.change_pct.toFixed(2)}
                            %
                          </span>
                        ) : (
                          '—'
                        )}
                      </TableCell>
                      <TableCell numeric>{nf(q?.pe_ttm ?? q?.pe)}</TableCell>
                      <TableCell numeric>{nf(q?.pb)}</TableCell>
                      <TableCell numeric>
                        {q?.dv_ttm != null ? nf(q.dv_ttm) + '%' : '—'}
                      </TableCell>
                      <TableCell numeric>{fmtMv(q?.total_mv || null)}</TableCell>
                      <TableCell>
                        {editNoteId === it.id ? (
                          <input
                            className="watchlist__note-input"
                            value={editNoteVal}
                            autoFocus
                            onChange={(e) => setEditNoteVal(e.target.value)}
                            onBlur={() => saveNote(it)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') saveNote(it);
                              if (e.key === 'Escape') setEditNoteId(null);
                            }}
                          />
                        ) : (
                          <span
                            className="watchlist__note"
                            onClick={() => {
                              setEditNoteId(it.id);
                              setEditNoteVal(it.note || '');
                            }}>
                            {it.note || <em>添加备注</em>}
                          </span>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="watchlist__row-actions">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setMovingItem(it)}>
                            移到
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleRemove(it)}>
                            删除
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </>
      )}
      {!activeGroup && !loading && (
        <StateView state="empty" text="选择或新建一个分组开始管理自选股。" />
      )}

      {/* 跨组移动 */}
      <Modal open={!!movingItem} onClose={() => setMovingItem(null)} size="sm">
        <ModalHeader>
          <ModalTitle>移动「{quotes[movingItem?.symbol || '']?.name || movingItem?.symbol}」到</ModalTitle>
        </ModalHeader>
        <ModalBody>
          <div className="watchlist__move-list">
            {otherGroups.map((g) => (
              <Button
                key={g.id}
                variant="secondary"
                fullWidth
                onClick={() => handleMove(g.id)}>
                {g.name} ({g.item_count})
              </Button>
            ))}
            {otherGroups.length === 0 && (
              <StateView state="empty" text="没有其它分组" />
            )}
          </div>
        </ModalBody>
      </Modal>

      {/* 新建分组 */}
      <Modal open={creating} onClose={() => setCreating(false)} size="sm">
        <ModalHeader>
          <ModalTitle>新建分组</ModalTitle>
        </ModalHeader>
        <ModalBody>
          <Input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="如：高股息 / 科技ETF / 港股通"
            autoFocus
          />
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" onClick={() => setCreating(false)}>
            取消
          </Button>
          <Button variant="primary" onClick={handleCreate}>
            创建
          </Button>
        </ModalFooter>
      </Modal>

      {/* 改名 */}
      <Modal open={!!renaming} onClose={() => setRenaming(null)} size="sm">
        <ModalHeader>
          <ModalTitle>重命名分组</ModalTitle>
        </ModalHeader>
        <ModalBody>
          <Input
            value={renameVal}
            onChange={(e) => setRenameVal(e.target.value)}
            autoFocus
          />
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" onClick={() => setRenaming(null)}>
            取消
          </Button>
          <Button variant="primary" onClick={handleRename}>
            保存
          </Button>
        </ModalFooter>
      </Modal>

      {/* 删除确认 */}
      <Modal open={!!deleting} onClose={() => setDeleting(null)} size="sm">
        <ModalHeader>
          <ModalTitle>删除分组</ModalTitle>
        </ModalHeader>
        <ModalBody>
          确定删除分组「{deleting?.name}」？组内所有股票会一并删除，且不可恢复。
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" onClick={() => setDeleting(null)}>
            取消
          </Button>
          <Button variant="danger" onClick={handleDelete}>
            删除
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};
