/**
 * BI 自定义对比看板页。
 * 顶栏:看板切换/新建/重命名/删除 + 全局时间范围 + 添加卡片 + 保存状态。
 * 画布:BoardCanvas;卡片内容由 renderCard 按类型分发。
 */
import React, {useEffect, useState} from 'react';
import {Button, Modal, StateView} from '../../components/ui';
import {useBoards} from './useBoards';
import {BoardCanvas} from './BoardCanvas';
import {PRESET_OPTIONS, PresetKey, resolveDateRange, uuid} from './boardTypes';
import {AddCardModal} from './AddCardModal';
import {
  KlineIndicatorMenuItems,
  KlineIndicatorParamsModal,
} from './KlineIndicatorMenu';
import {KlineCard} from './cards/KlineCard';
import {FinancialTrendCard} from './cards/FinancialTrendCard';
import {MetricCard} from './cards/MetricCard';
import {IndexPeCard} from './cards/IndexPeCard';
import './Board.css';

export const Board: React.FC = () => {
  const boards = useBoards((s) => s.boards);
  const activeId = useBoards((s) => s.activeId);
  const layout = useBoards((s) => s.layout);
  const loading = useBoards((s) => s.loading);
  const loadError = useBoards((s) => s.loadError);
  const saveState = useBoards((s) => s.saveState);
  const loadBoards = useBoards((s) => s.loadBoards);
  const selectBoard = useBoards((s) => s.selectBoard);
  const createBoard = useBoards((s) => s.createBoard);
  const renameBoard = useBoards((s) => s.renameBoard);
  const deleteBoard = useBoards((s) => s.deleteBoard);
  const retrySave = useBoards((s) => s.retrySave);
  const flushSave = useBoards((s) => s.flushSave);
  const setTimeRange = useBoards((s) => s.setTimeRange);
  const updateCard = useBoards((s) => s.updateCard);
  const removeCard = useBoards((s) => s.removeCard);
  const bringToFront = useBoards((s) => s.bringToFront);
  const sendToBack = useBoards((s) => s.sendToBack);

  const [addOpen, setAddOpen] = useState(false);
  const [dlg, setDlg] = useState<'create' | 'rename' | 'delete' | null>(null);
  const [nameInput, setNameInput] = useState('');
  const [nameError, setNameError] = useState<string | null>(null);
  const [refreshMap, setRefreshMap] = useState<Record<string, number>>({});
  const [paramsCardId, setParamsCardId] = useState<string | null>(null);

  useEffect(() => {
    void loadBoards();
  }, [loadBoards]);

  // 离开页面前把挂起的保存刷出去
  useEffect(() => () => { void flushSave(); }, [flushSave]);

  const bumpRefresh = (id: string) =>
    setRefreshMap((m) => ({...m, [id]: (m[id] || 0) + 1}));

  const duplicateCard = (id: string) => {
    const c = layout.cards.find((x) => x.id === id);
    if (!c) return;
    useBoards.getState().addCard({
      ...c,
      id: uuid(),
      x: c.x + 1,
      y: c.y + 1,
      z: layout.maxZ + 1,
    });
  };

  const submitName = async () => {
    setNameError(null);
    if (!nameInput.trim()) { setNameError('请输入名称'); return; }
    const ok = dlg === 'create'
      ? await createBoard(nameInput.trim())
      : await renameBoard(nameInput.trim());
    if (!ok) { setNameError('保存失败:名称可能已存在'); return; }
    setDlg(null);
    setNameInput('');
  };

  const tr = layout.timeRange;

  const saveLabel =
    saveState === 'saving' ? '保存中…'
    : saveState === 'error' ? '保存失败·点击重试'
    : saveState === 'saved' ? '已保存' : '';

  return (
    <div className="board-page">
      <div className="board-topbar">
        <div className="board-topbar__group">
          <select
            className="board-select"
            value={activeId ?? ''}
            onChange={(e) => { if (e.target.value) void selectBoard(Number(e.target.value)); }}
          >
            {boards.length === 0 && <option value="">暂无看板</option>}
            {boards.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
          <Button size="sm" onClick={() => { setNameInput(''); setNameError(null); setDlg('create'); }}>
            新建
          </Button>
          <Button size="sm" disabled={!activeId}
            onClick={() => { setNameInput(boards.find((b) => b.id === activeId)?.name || ''); setNameError(null); setDlg('rename'); }}>
            重命名
          </Button>
          <Button size="sm" variant="danger" disabled={!activeId} onClick={() => setDlg('delete')}>
            删除
          </Button>
        </div>

        <div className="board-topbar__group">
          <div className="board-chips">
            {PRESET_OPTIONS.map((p) => (
              <button
                key={p.key}
                type="button"
                className={`board-chip ${tr.preset === p.key ? 'board-chip--active' : ''}`}
                onClick={() => setTimeRange({...tr, preset: p.key as PresetKey})}
              >
                {p.label}
              </button>
            ))}
          </div>
          {tr.preset === 'custom' && (
            <div className="board-daterange">
              <input type="date" value={tr.start || ''}
                onChange={(e) => setTimeRange({...tr, start: e.target.value || null})} />
              <span>至</span>
              <input type="date" value={tr.end || ''}
                onChange={(e) => setTimeRange({...tr, end: e.target.value || null})} />
            </div>
          )}
        </div>

        <div className="board-topbar__spacer" />

        <div className="board-topbar__group">
          <Button size="sm" variant="primary" disabled={!activeId} onClick={() => setAddOpen(true)}>
            + 添加卡片
          </Button>
          {saveLabel && (
            <span
              className={`board-savestate board-savestate--${saveState}`}
              onClick={() => { if (saveState === 'error') void retrySave(); }}
            >
              <span className="board-savestate__dot" />
              {saveLabel}
            </span>
          )}
        </div>
      </div>

      {loading ? (
        <StateView state="loading" />
      ) : loadError ? (
        <StateView state="error" text={loadError} onRetry={() => void loadBoards()} />
      ) : boards.length === 0 ? (
        <StateView state="empty" text="还没有看板,点击「新建」创建一个" />
      ) : (
        <BoardCanvas
          layout={layout}
          renderCard={(card) => {
            const range = resolveDateRange(layout.timeRange);
            const refreshKey = refreshMap[card.id] || 0;
            switch (card.type) {
              case 'kline':
                return (
                  <KlineCard
                    symbol={card.symbol}
                    config={card.config}
                    range={range}
                    refreshKey={refreshKey}
                  />
                );
              case 'financial_trend':
                return (
                  <FinancialTrendCard
                    symbol={card.symbol}
                    config={card.config}
                    range={range}
                    refreshKey={refreshKey}
                  />
                );
              case 'metric':
                return (
                  <MetricCard
                    symbol={card.symbol}
                    config={card.config}
                    range={range}
                    refreshKey={refreshKey}
                  />
                );
              case 'index_pe':
                return (
                  <IndexPeCard
                    config={card.config}
                    range={range}
                    refreshKey={refreshKey}
                  />
                );
              default:
                return (
                  <div className="board-card__placeholder">{card.title}</div>
                );
            }
          }}
          onCardChange={updateCard}
          onFocusCard={bringToFront}
          onRemoveCard={removeCard}
          onDuplicateCard={duplicateCard}
          onOpacityCard={(id, v) => updateCard(id, {opacity: v})}
          onSendToBackCard={sendToBack}
          onRefreshCard={bumpRefresh}
          renderMenuExtras={(card, close) => {
            if (card.type !== 'kline') return null;
            return (
              <KlineIndicatorMenuItems
                card={card}
                onToggle={(k) => updateCard(card.id, {
                  config: {
                    ...card.config,
                    indicators: {...card.config.indicators, [k]: !card.config.indicators[k]},
                  },
                })}
                onOpenParams={() => { setParamsCardId(card.id); close(); }}
              />
            );
          }}
        />
      )}

      <AddCardModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        layout={layout}
        onAdd={(card) => useBoards.getState().addCard(card)}
      />

      {(() => {
        const pc = layout.cards.find((c) => c.id === paramsCardId && c.type === 'kline');
        if (!pc || pc.type !== 'kline') return null;
        return (
          <KlineIndicatorParamsModal
            open
            config={pc.config}
            onClose={() => setParamsCardId(null)}
            onSave={(config) => updateCard(pc.id, {config})}
          />
        );
      })()}

      <Modal
        open={dlg === 'create' || dlg === 'rename'}
        title={dlg === 'create' ? '新建看板' : '重命名看板'}
        onClose={() => setDlg(null)}
        width={360}
        footer={
          <>
            <Button size="sm" onClick={() => setDlg(null)}>取消</Button>
            <Button size="sm" variant="primary" onClick={() => void submitName()}>确定</Button>
          </>
        }
      >
        <input
          className="board-input"
          placeholder="看板名称"
          value={nameInput}
          onChange={(e) => setNameInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') void submitName(); }}
          autoFocus
        />
        {nameError && <div className="board-dialog-error">{nameError}</div>}
      </Modal>

      <Modal
        open={dlg === 'delete'}
        title="删除看板"
        onClose={() => setDlg(null)}
        width={360}
        footer={
          <>
            <Button size="sm" onClick={() => setDlg(null)}>取消</Button>
            <Button size="sm" variant="danger"
              onClick={() => { void deleteBoard(); setDlg(null); }}>
              删除
            </Button>
          </>
        }
      >
        <div style={{fontSize: 13}}>确定删除该看板及其全部卡片布局?不可恢复。</div>
      </Modal>
    </div>
  );
};
