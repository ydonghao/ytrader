/**
 * 添加卡片弹窗 — 左侧 4 类卡片,右侧类型相关配置(标的/指标/指数),
 * 确定后组装 BoardCard(z=++maxZ,首个空网格位)回调 onAdd。
 */
import React, {useEffect, useState} from 'react';
import {Button, Modal} from '../../components/ui';
import {
  BoardCard,
  BoardLayout,
  CardType,
  DEFAULT_SIZE,
  DEFAULT_TREND_METRICS,
  FINANCIAL_METRICS,
  INDEX_PE_LIST,
  findFreeSlot,
  uuid,
  defaultKlineConfig,
} from './boardTypes';
import {SymbolPicker, SymbolPick} from './SymbolPicker';

interface AddCardModalProps {
  open: boolean;
  onClose: () => void;
  layout: BoardLayout;
  onAdd: (card: BoardCard) => void;
}

const CARD_TYPES: {key: CardType; label: string; desc: string}[] = [
  {key: 'kline', label: 'K线走势', desc: '蜡烛图+成交量,叠加对比主角'},
  {key: 'financial_trend', label: '财务趋势', desc: '多期财务指标折线'},
  {key: 'metric', label: '指标数值', desc: '最新值+同比大字卡'},
  {key: 'index_pe', label: '指数PE', desc: '宽基市盈率+均值/±σ参考线'},
];

export const AddCardModal: React.FC<AddCardModalProps> = ({
  open, onClose, layout, onAdd,
}) => {
  const [type, setType] = useState<CardType>('kline');
  const [pick, setPick] = useState<SymbolPick | null>(null);
  const [metrics, setMetrics] = useState<string[]>(DEFAULT_TREND_METRICS);
  const [metric, setMetric] = useState<string>(DEFAULT_TREND_METRICS[0]);
  const [peCode, setPeCode] = useState<string>(INDEX_PE_LIST[0].code);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setType('kline');
      setPick(null);
      setMetrics(DEFAULT_TREND_METRICS);
      setMetric(DEFAULT_TREND_METRICS[0]);
      setPeCode(INDEX_PE_LIST[0].code);
      setError(null);
    }
  }, [open]);

  const needSymbol = type !== 'index_pe';

  const confirm = () => {
    setError(null);
    if (needSymbol && !pick) { setError('请选择标的'); return; }
    if (type === 'financial_trend' && metrics.length === 0) {
      setError('请至少选择一个指标'); return;
    }
    const size = DEFAULT_SIZE[type];
    const slot = findFreeSlot(layout.cards, size.w, size.h);
    const z = layout.maxZ + 1;
    const base = {
      id: uuid(), x: slot.x, y: slot.y,
      w: size.w, h: size.h, z, opacity: 1,
    };
    let card: BoardCard;
    if (type === 'kline') {
      card = {...base, type, title: pick!.name, symbol: pick!.symbol, config: defaultKlineConfig()};
    } else if (type === 'financial_trend') {
      card = {...base, type, title: pick!.name, symbol: pick!.symbol,
        config: {metrics}};
    } else if (type === 'metric') {
      card = {...base, type, title: pick!.name, symbol: pick!.symbol,
        config: {metric}};
    } else {
      card = {...base, type, title: INDEX_PE_LIST.find((i) => i.code === peCode)!.name,
        symbol: null, config: {code: peCode}};
    }
    onAdd(card);
    onClose();
  };

  const toggleMetric = (key: string) => {
    setMetrics((ms) =>
      ms.includes(key) ? ms.filter((k) => k !== key) : [...ms, key],
    );
  };

  return (
    <Modal open={open} title="添加卡片" onClose={onClose} width={560}
      footer={
        <>
          <Button size="sm" onClick={onClose}>取消</Button>
          <Button size="sm" variant="primary" onClick={confirm}>添加</Button>
        </>
      }
    >
      <div className="board-addcard">
        <div className="board-addcard__types">
          {CARD_TYPES.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`board-addcard__type ${type === t.key ? 'board-addcard__type--active' : ''}`}
              onClick={() => setType(t.key)}
            >
              <span className="board-addcard__type-label">{t.label}</span>
              <span className="board-addcard__type-desc">{t.desc}</span>
            </button>
          ))}
        </div>
        <div className="board-addcard__config">
          {needSymbol && (
            <div className="board-addcard__field">
              <label>标的</label>
              <SymbolPicker value={pick} onChange={setPick} />
            </div>
          )}
          {type === 'financial_trend' && (
            <div className="board-addcard__field">
              <label>指标(可多选)</label>
              <div className="board-addcard__metrics">
                {FINANCIAL_METRICS.map((m) => (
                  <label key={m.key} className="board-addcard__metric">
                    <input type="checkbox" checked={metrics.includes(m.key)}
                      onChange={() => toggleMetric(m.key)} />
                    {m.label}
                  </label>
                ))}
              </div>
            </div>
          )}
          {type === 'metric' && (
            <div className="board-addcard__field">
              <label>指标</label>
              <select className="board-select" value={metric}
                onChange={(e) => setMetric(e.target.value)}>
                {FINANCIAL_METRICS.map((m) => (
                  <option key={m.key} value={m.key}>{m.label}</option>
                ))}
              </select>
            </div>
          )}
          {type === 'index_pe' && (
            <div className="board-addcard__field">
              <label>宽基指数</label>
              <select className="board-select" value={peCode}
                onChange={(e) => setPeCode(e.target.value)}>
                {INDEX_PE_LIST.map((i) => (
                  <option key={i.code} value={i.code}>{i.name}</option>
                ))}
              </select>
            </div>
          )}
          {error && <div className="board-dialog-error">{error}</div>}
        </div>
      </div>
    </Modal>
  );
};
