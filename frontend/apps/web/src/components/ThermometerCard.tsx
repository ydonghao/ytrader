/**
 * ThermometerCard — 市场温度计共享组件（数据自取）。
 * full:温度行 + 水位回测结论 + ERP 历史曲线(懒加载展开);
 * compact:一行精简条(Thesis 顶部),整条深链 /indices?tab=thermo。
 */
import {useEffect, useState} from 'react';
import {Link} from 'react-router-dom';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip,
} from 'recharts';
import {axisProps, tooltipProps} from '../lib/chartTheme';
import {getApiBase} from '../lib/api';
import './ThermometerCard.css';

const API = `${getApiBase()}/thesis`;

export function ThermometerCard({variant = 'full'}: {variant?: 'full' | 'compact'}) {
  const [thermo, setThermo] = useState<any>(null);
  const [thermoBt, setThermoBt] = useState<any>(null);
  const [thermoHist, setThermoHist] = useState<any[] | null>(null);

  useEffect(() => {
    fetch(`${API}/thermometer`).then(r => r.json())
      .then(d => d.code === 0 && setThermo(d.data)).catch(() => {});
    fetch(`${API}/thermometer/backtest`).then(r => r.json())
      .then(d => d.code === 0 && setThermoBt(d.data)).catch(() => {});
  }, []);

  function loadThermoHist() {
    if (thermoHist) return;
    fetch(`${API}/thermometer/history?days=2000`).then(r => r.json())
      .then(d => d.code === 0 && setThermoHist(d.data)).catch(() => {});
  }

  if (!thermo || !thermo.level || thermo.level === 'unknown') return null;

  if (variant === 'compact') {
    return (
      <Link to="/indices?tab=thermo" className={`thermo-card thermo-card--compact thermo-card--${thermo.level}`}>
        <span className="thermo-card__label">🌡 {thermo.level_label}</span>
        <span>股债性价比 {thermo.erp_pct}%{thermo.erp_percentile != null && `（分位 ${thermo.erp_percentile}%）`}</span>
        {thermo.position_band && (
          <span className="thermo-card__band">
            建议仓位 {thermo.position_band.low}~{thermo.position_band.high}%
          </span>
        )}
        <span className="thermo-card__toggle">市场温度页 →</span>
      </Link>
    );
  }

  return (
    <div className={`thermo-card thermo-card--${thermo.level}`}>
      <div className="thermo-card__row" onClick={loadThermoHist} style={{cursor: 'pointer'}}>
        <span className="thermo-card__label">🌡 {thermo.level_label}</span>
        <span>股债性价比 {thermo.erp_pct}%{thermo.erp_percentile != null &&
          `（分位 ${thermo.erp_percentile}%）`}</span>
        {thermo.buffett_pct != null && (
          <span>巴菲特指标 {thermo.buffett_pct}%（{thermo.buffett_label}）</span>
        )}
        {thermo.position_band && (
          <span className="thermo-card__band">
            建议整体仓位水位 {thermo.position_band.low}~{thermo.position_band.high}%
          </span>
        )}
        <span className="thermo-card__toggle">
          {thermoHist ? '收起历史 ▴' : '展开历史 ▾'}
        </span>
      </div>
      {thermoBt && (
        <p className="dim" style={{marginTop: 'var(--space-1)'}}>
          水位策略回测（{thermoBt.start?.slice(0, 4)}-{thermoBt.end?.slice(0, 4)}）：
          年化 <b style={{color: 'var(--color-success)'}}>{thermoBt.strategy?.cagr_pct}%</b>
          / 回撤 {thermoBt.strategy?.max_drawdown_pct}%
          vs 买入持有 {thermoBt.buy_hold?.cagr_pct}% / {thermoBt.buy_hold?.max_drawdown_pct}%
        </p>
      )}
      {thermoHist && (
        <div style={{height: 180, marginTop: 'var(--space-2)'}}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={thermoHist}>
              <XAxis dataKey="trade_date" {...axisProps} minTickGap={80} />
              <YAxis {...axisProps} domain={['auto', 'auto']}
                     tickFormatter={(v: number) => v.toFixed(1) + '%'} />
              <Tooltip {...tooltipProps} formatter={(v: number) => [v + '%', 'ERP']} />
              <Line type="monotone" dataKey="erp_pct" dot={false} strokeWidth={1.5}
                    stroke="var(--color-accent, #5e5ce6)" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
