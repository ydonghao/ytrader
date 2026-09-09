/**
 * 看板画布 — 相对定位容器 + 网格底纹;卡片按 z 升序渲染,
 * z-index 决定叠加层级;画布高度随最底卡片自动增高。
 */
import React, {useEffect, useRef, useState} from 'react';
import {BoardCard, BoardLayout, GRID_ROW_PX} from './boardTypes';
import {BoardCardShell} from './BoardCardShell';

export interface BoardCanvasProps {
  layout: BoardLayout;
  renderCard: (card: BoardCard) => React.ReactNode;
  onCardChange: (id: string, patch: Partial<BoardCard>) => void;
  onFocusCard: (id: string) => void;
  onRemoveCard: (id: string) => void;
  onDuplicateCard: (id: string) => void;
  onOpacityCard: (id: string, v: number) => void;
  onSendToBackCard: (id: string) => void;
  onRefreshCard: (id: string) => void;
  renderMenuExtras?: (card: BoardCard, close: () => void) => React.ReactNode;
}

export const BoardCanvas: React.FC<BoardCanvasProps> = ({
  layout, renderCard, onCardChange, onFocusCard, onRemoveCard,
  onDuplicateCard, onOpacityCard, onSendToBackCard, onRefreshCard,
  renderMenuExtras,
}) => {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [canvasWidth, setCanvasWidth] = useState(0);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setCanvasWidth(el.clientWidth));
    ro.observe(el);
    setCanvasWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const bottom = layout.cards.reduce((m, c) => Math.max(m, c.y + c.h), 0);
  const contentHeight = Math.max(bottom * GRID_ROW_PX + 48, 600);

  const cards = [...layout.cards].sort((a, b) => a.z - b.z);

  return (
    <div
      ref={canvasRef}
      className="board-canvas"
      style={{height: contentHeight}}
    >
      {canvasWidth > 0 &&
        cards.map((card) => (
          <BoardCardShell
            key={card.id}
            card={card}
            canvasWidth={canvasWidth}
            onChange={(patch) => onCardChange(card.id, patch)}
            onFocus={() => onFocusCard(card.id)}
            onRemove={() => onRemoveCard(card.id)}
            onDuplicate={() => onDuplicateCard(card.id)}
            onOpacity={(v) => onOpacityCard(card.id, v)}
            onSendToBack={() => onSendToBackCard(card.id)}
            onRefresh={() => onRefreshCard(card.id)}
            menuExtras={renderMenuExtras && ((close) => renderMenuExtras(card, close))}
          >
            {renderCard(card)}
          </BoardCardShell>
        ))}
    </div>
  );
};
