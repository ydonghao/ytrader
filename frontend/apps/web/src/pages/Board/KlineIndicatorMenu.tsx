/**
 * K线卡技术指标菜单区 — 勾选行写 config 即时生效;"指标参数…"由 index.tsx
 * 持有弹窗状态(弹窗 portal 在 body,若挂菜单内会被菜单外点关闭连带卸载)。
 */
import React, {useState} from 'react';
import {Button, Modal} from '../../components/ui';
import {KlineCardData, KlineIndicatorConfig, normalizeKlineConfig} from './boardTypes';

/** ⋯菜单内的勾选行 + 参数入口(经 BoardCardShell.menuExtras 注入) */
export const KlineIndicatorMenuItems: React.FC<{
  card: KlineCardData;
  onToggle: (k: 'macd' | 'rsi' | 'boll') => void;
  onOpenParams: () => void;
}> = ({card, onToggle, onOpenParams}) => {
  const ind = card.config.indicators;
  const rows: {key: 'macd' | 'rsi' | 'boll'; label: string}[] = [
    {key: 'macd', label: 'MACD'},
    {key: 'rsi', label: 'RSI'},
    {key: 'boll', label: '布林带'},
  ];
  return (
    <>
      <div className="board-card__menu-sep" />
      {rows.map((r) => (
        <button
          key={r.key}
          type="button"
          className={`board-card__menu-item board-card__menu-check ${ind[r.key] ? 'board-card__menu-check--on' : ''}`}
          onClick={() => onToggle(r.key)}
        >
          <span className="board-card__menu-checkmark">{ind[r.key] ? '✓' : ''}</span>
          {r.label}
        </button>
      ))}
      <button type="button" className="board-card__menu-item" onClick={onOpenParams}>
        指标参数…
      </button>
    </>
  );
};

interface ParamFieldProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
}

const ParamField: React.FC<ParamFieldProps> = ({label, value, onChange}) => (
  <label className="board-param__field">
    <span>{label}</span>
    <input
      className="board-input"
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  </label>
);

/** 指标参数弹窗(index.tsx 持状态渲染;非法输入禁用确定并红字提示) */
export const KlineIndicatorParamsModal: React.FC<{
  open: boolean;
  config: KlineIndicatorConfig;
  onClose: () => void;
  onSave: (c: KlineIndicatorConfig) => void;
}> = ({open, config, onClose, onSave}) => {
  const [macd, setMacd] = useState({fast: '', slow: '', signal: ''});
  const [rsiP, setRsiP] = useState('');
  const [bollP, setBollP] = useState({period: '', stdDev: ''});
  const [error, setError] = useState<string | null>(null);
  const [loadedFor, setLoadedFor] = useState<boolean | null>(null);

  // 弹窗每次打开,用当前 config 回填
  if (open && loadedFor !== true) {
    setMacd({
      fast: String(config.params.macd.fast),
      slow: String(config.params.macd.slow),
      signal: String(config.params.macd.signal),
    });
    setRsiP(String(config.params.rsi.period));
    setBollP({period: String(config.params.boll.period), stdDev: String(config.params.boll.stdDev)});
    setError(null);
    setLoadedFor(true);
  }
  if (!open && loadedFor !== false) setLoadedFor(false);

  const save = () => {
    const next = normalizeKlineConfig({
      ...config,
      params: {
        macd: {fast: Number(macd.fast), slow: Number(macd.slow), signal: Number(macd.signal)},
        rsi: {period: Number(rsiP)},
        boll: {period: Number(bollP.period), stdDev: Number(bollP.stdDev)},
      },
    });
    // normalize 后与输入不一致 = 有非法值被回默认,提示而非静默吞掉
    const inMacd = Number(macd.fast) === next.params.macd.fast
      && Number(macd.slow) === next.params.macd.slow
      && Number(macd.signal) === next.params.macd.signal;
    const inRsi = Number(rsiP) === next.params.rsi.period;
    const sdOk = isFinite(Number(bollP.stdDev)) && Number(bollP.stdDev) === next.params.boll.stdDev;
    const bollPeriodOk = Number(bollP.period) === next.params.boll.period;
    if (!inMacd || !inRsi || !sdOk || !bollPeriodOk) {
      setError('参数需为整数 2–250(fast<slow),stdDev 0.5–5');
      return;
    }
    onSave(next);
    onClose();
  };

  return (
    <Modal
      open={open}
      title="指标参数"
      onClose={onClose}
      width={360}
      footer={
        <>
          <Button size="sm" onClick={onClose}>取消</Button>
          <Button size="sm" variant="primary" onClick={save}>确定</Button>
        </>
      }
    >
      <div className="board-param">
        <div className="board-param__group">
          <div className="board-param__group-title">MACD</div>
          <ParamField label="快线" value={macd.fast} onChange={(v) => setMacd((s) => ({...s, fast: v}))} />
          <ParamField label="慢线" value={macd.slow} onChange={(v) => setMacd((s) => ({...s, slow: v}))} />
          <ParamField label="信号" value={macd.signal} onChange={(v) => setMacd((s) => ({...s, signal: v}))} />
        </div>
        <div className="board-param__group">
          <div className="board-param__group-title">RSI</div>
          <ParamField label="周期" value={rsiP} onChange={setRsiP} />
        </div>
        <div className="board-param__group">
          <div className="board-param__group-title">布林带</div>
          <ParamField label="周期" value={bollP.period} onChange={(v) => setBollP((s) => ({...s, period: v}))} />
          <ParamField label="标准差倍数" value={bollP.stdDev} onChange={(v) => setBollP((s) => ({...s, stdDev: v}))} />
        </div>
        {error && <div className="board-dialog-error">{error}</div>}
      </div>
    </Modal>
  );
};
