/**
 * 看板卡片壳 — 绝对定位、头部拖拽、右下角缩放、⋯菜单(透明度/复制/置顶/置底/刷新/删除)。
 *
 * 拖拽/缩放:pointer events + setPointerCapture;默认坐标四舍五入吸附
 * 网格,按住 Alt 保留小数自由定位(可中途按/放 Alt 切换);拖拽期间用
 * 本地 state 覆盖渲染,pointerup 才经 onChange 提交 store(自动保存节流)。
 */
import React, {useEffect, useRef, useState} from 'react';
import {
  BoardCard,
  GRID_COLS,
  GRID_ROW_PX,
  MIN_H,
  MIN_W,
} from './boardTypes';

export interface BoardCardShellProps {
  card: BoardCard;
  canvasWidth: number;
  onChange: (patch: Partial<BoardCard>) => void;
  onFocus: () => void;
  onRemove: () => void;
  onDuplicate: () => void;
  onOpacity: (v: number) => void;
  onSendToBack: () => void;
  onRefresh?: () => void;
  menuExtras?: (close: () => void) => React.ReactNode;
  children: React.ReactNode;
}

type Mode = 'drag' | 'resize' | null;

export const BoardCardShell: React.FC<BoardCardShellProps> = ({
  card, canvasWidth, onChange, onFocus, onRemove, onDuplicate,
  onOpacity, onSendToBack, onRefresh, menuExtras, children,
}) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const [mode, setMode] = useState<Mode>(null);
  const [view, setView] = useState({x: card.x, y: card.y, w: card.w, h: card.h});
  const liveRef = useRef({x: card.x, y: card.y, w: card.w, h: card.h});
  const gestureRef = useRef<{
    startX: number; startY: number;
    origX: number; origY: number; origW: number; origH: number;
  } | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  // 菜单外点关闭(StockSelect 同款模式)
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [menuOpen]);

  // 非手势期间,store 里的位置变化(换看板/复制/兜底)同步到本地视图
  useEffect(() => {
    if (!mode) setView({x: card.x, y: card.y, w: card.w, h: card.h});
  }, [card.x, card.y, card.w, card.h, mode]);

  const colPx = canvasWidth / GRID_COLS;

  const beginGesture = (e: React.PointerEvent, m: Mode) => {
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    liveRef.current = {x: card.x, y: card.y, w: card.w, h: card.h};
    setView({x: card.x, y: card.y, w: card.w, h: card.h});
    gestureRef.current = {
      startX: e.clientX, startY: e.clientY,
      origX: card.x, origY: card.y, origW: card.w, origH: card.h,
    };
    setMode(m);
  };

  const moveGesture = (e: React.PointerEvent) => {
    const g = gestureRef.current;
    if (!g) return;
    if (mode === 'drag') {
      let nx = g.origX + (e.clientX - g.startX) / colPx;
      let ny = g.origY + (e.clientY - g.startY) / GRID_ROW_PX;
      if (!e.altKey) { nx = Math.round(nx); ny = Math.round(ny); }
      nx = Math.min(Math.max(nx, 0), GRID_COLS - g.origW);
      ny = Math.max(ny, 0);
      liveRef.current.x = nx;
      liveRef.current.y = ny;
    } else if (mode === 'resize') {
      let nw = g.origW + (e.clientX - g.startX) / colPx;
      let nh = g.origH + (e.clientY - g.startY) / GRID_ROW_PX;
      if (!e.altKey) { nw = Math.round(nw); nh = Math.round(nh); }
      nw = Math.min(Math.max(nw, MIN_W), GRID_COLS - g.origX);
      nh = Math.max(nh, MIN_H);
      liveRef.current.w = nw;
      liveRef.current.h = nh;
    }
    setView({...liveRef.current});
  };

  const endGesture = () => {
    if (!gestureRef.current) return;
    gestureRef.current = null;
    setMode(null);
    const {x, y, w, h} = liveRef.current;
    if (x !== card.x || y !== card.y || w !== card.w || h !== card.h) {
      onChange({x, y, w, h});
    }
  };

  return (
    <div
      className={`board-card ${mode ? 'board-card--active' : ''}`}
      style={{
        left: `${(view.x / GRID_COLS) * 100}%`,
        top: view.y * GRID_ROW_PX,
        width: `${(view.w / GRID_COLS) * 100}%`,
        height: view.h * GRID_ROW_PX,
        zIndex: card.z,
        opacity: card.opacity,
      }}
      onPointerDown={() => onFocus()}
    >
      <div
        className="board-card__header"
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).closest('.board-card__menu')) return;
          beginGesture(e, 'drag');
        }}
        onPointerMove={mode === 'drag' ? moveGesture : undefined}
        onPointerUp={endGesture}
        onPointerCancel={endGesture}
        title="拖动移动;按住 Alt 自由定位(可叠加)"
      >
        <span className="board-card__title" title={card.title}>{card.title}</span>
        <div className="board-card__menu" ref={menuRef}>
          <button
            type="button"
            className="board-card__menubtn"
            onClick={() => setMenuOpen((v) => !v)}
            title="卡片菜单"
          >
            ⋯
          </button>
          {menuOpen && (
            <div className="board-card__menu-list">
              <label className="board-card__menu-item board-card__menu-opacity">
                透明度
                <input
                  type="range"
                  min={0.15}
                  max={1}
                  step={0.05}
                  value={card.opacity}
                  onChange={(e) => onOpacity(Number(e.target.value))}
                />
                <span>{Math.round(card.opacity * 100)}%</span>
              </label>
              <button type="button" className="board-card__menu-item"
                onClick={() => { onRefresh?.(); setMenuOpen(false); }}
                disabled={!onRefresh}>
                刷新数据
              </button>
              <button type="button" className="board-card__menu-item"
                onClick={() => { onDuplicate(); setMenuOpen(false); }}>
                复制卡片
              </button>
              {menuExtras?.(() => setMenuOpen(false))}
              <button type="button" className="board-card__menu-item"
                onClick={() => { onFocus(); setMenuOpen(false); }}>
                置顶
              </button>
              <button type="button" className="board-card__menu-item"
                onClick={() => { onSendToBack(); setMenuOpen(false); }}>
                置底
              </button>
              <button type="button" className="board-card__menu-item board-card__menu-item--danger"
                onClick={() => { onRemove(); setMenuOpen(false); }}>
                删除
              </button>
            </div>
          )}
        </div>
      </div>
      <div className="board-card__body">{children}</div>
      <div
        className="board-card__resize"
        title="拖动缩放;按住 Alt 自由尺寸"
        onPointerDown={(e) => beginGesture(e, 'resize')}
        onPointerMove={mode === 'resize' ? moveGesture : undefined}
        onPointerUp={endGesture}
        onPointerCancel={endGesture}
      >
        <svg width="10" height="10" viewBox="0 0 10 10">
          <path d="M9 1v8H1" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </div>
    </div>
  );
};
