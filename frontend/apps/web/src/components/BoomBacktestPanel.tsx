// frontend/apps/web/src/components/BoomBacktestPanel.tsx
/** 策略验证:回测「业绩大增(+文本命中)→ T+1 买入持有N月」历史表现。 */
import {useState} from 'react';
import {getApiBase} from '../lib/api';
import {Button, Card, StateView} from './ui';
import {CATEGORY_LABELS} from '../pages/EarningsRadar.categories';

const API_BASE = getApiBase();

interface YearRow { year: number; n: number; avg_ret: number; avg_bench_ret: number; avg_excess: number; hit_rate: number; }
interface CatRow { category: string; n: number; avg_ret: number; avg_excess: number; }
interface Report {
  n_events: number; n_traded: number; n_skipped_limitup: number; n_no_data: number;
  avg_ret: number; avg_bench_ret: number; avg_excess: number; hit_rate: number;
  by_year: YearRow[]; by_category: CatRow[]; meta: Record<string, unknown>;
}

export function BoomBacktestPanel() {
  const thisYear = new Date().getFullYear();
  const [startYear, setStartYear] = useState(thisYear - 3);
  const [endYear, setEndYear] = useState(thisYear - 1);
  const [holdMonths, setHoldMonths] = useState(3);
  const [withText, setWithText] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/boom/backtest`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({start_year: startYear, end_year: endYear,
                              hold_months: holdMonths, with_text: withText}),
      });
      const j = await r.json();
      if (j.code === 0) setReport(j.data);
      else setError(j.msg || '回测失败');
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  };

  const fmt = (v: number) => (v > 0 ? '+' : '') + v.toFixed(2) + '%';

  return (
    <div className="bbp">
      <Card className="bbp-form" padding="compact">
        <label>起年 <input className="bbp-input" type="number" value={startYear}
          onChange={(e) => setStartYear(Number(e.target.value) || 0)} /></label>
        <label>止年 <input className="bbp-input" type="number" value={endYear}
          onChange={(e) => setEndYear(Number(e.target.value) || 0)} /></label>
        <label>持有月 <input className="bbp-input" type="number" min={1} max={12} value={holdMonths}
          onChange={(e) => setHoldMonths(Math.max(1, Math.min(12, Number(e.target.value) || 3)))} /></label>
        <label className="bbp-check">
          <input type="checkbox" checked={withText}
                 onChange={(e) => setWithText(e.target.checked)} />
          仅含文本命中
        </label>
        <Button variant="primary" onClick={run} loading={running}>运行回测</Button>
      </Card>

      {error && <StateView state="error" text={error} />}
      {!report && !error && !running && (
        <StateView state="empty" text="设置年份区间后运行回测" />
      )}

      {report && (
        <>
          <Card className="bbp-summary" padding="compact">
            样本 <b className="num">{report.n_events}</b> · 成交{' '}
            <b className="num">{report.n_traded}</b>(涨停跳过{' '}
            {report.n_skipped_limitup} / 无行情 {report.n_no_data}) ·
            平均收益 <b className={`num ${report.avg_ret >= 0 ? 'is-up' : 'is-down'}`}>
              {fmt(report.avg_ret)}</b> · 基准{' '}
            <b className="num">{fmt(report.avg_bench_ret)}</b> · 超额{' '}
            <b className={`num ${report.avg_excess >= 0 ? 'is-up' : 'is-down'}`}>
              {fmt(report.avg_excess)}</b> · 胜率{' '}
            <b className="num">{(report.hit_rate * 100).toFixed(1)}%</b>
          </Card>

          <table className="er-table">
            <thead><tr><th>年份</th><th>样本</th><th>平均收益</th><th>基准</th><th>超额</th><th>胜率</th></tr></thead>
            <tbody>
              {report.by_year.map((y) => (
                <tr key={y.year}>
                  <td className="num">{y.year}</td>
                  <td className="num">{y.n}</td>
                  <td className={`num ${y.avg_ret >= 0 ? 'is-up' : 'is-down'}`}>{fmt(y.avg_ret)}</td>
                  <td className="num">{fmt(y.avg_bench_ret)}</td>
                  <td className={`num ${y.avg_excess >= 0 ? 'is-up' : 'is-down'}`}>{fmt(y.avg_excess)}</td>
                  <td className="num">{(y.hit_rate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>

          {report.by_category.length > 0 && (
            <>
              <div className="bbp-subtitle">分信号分类</div>
              <table className="er-table">
                <thead><tr><th>分类</th><th>样本</th><th>平均收益</th><th>超额</th></tr></thead>
                <tbody>
                  {report.by_category.map((c) => (
                    <tr key={c.category}>
                      <td>{CATEGORY_LABELS[c.category] ?? c.category}</td>
                      <td className="num">{c.n}</td>
                      <td className={`num ${c.avg_ret >= 0 ? 'is-up' : 'is-down'}`}>{fmt(c.avg_ret)}</td>
                      <td className={`num ${c.avg_excess >= 0 ? 'is-up' : 'is-down'}`}>{fmt(c.avg_excess)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}

          <div className="bbp-meta">
            口径说明:{String(report.meta.text_leg ?? '')};
            {String(report.meta.disclosure_bias ?? '')};
            {String(report.meta.survivorship ?? '')}
          </div>
        </>
      )}
    </div>
  );
}
