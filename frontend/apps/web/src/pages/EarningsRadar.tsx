/** 财报季景气雷达:业绩大增 × 文本景气信号 候选池。 */
import {useMemo, useState} from 'react';
import {Button, Card, PageHeader, StateView, Tabs} from '../components/ui';
import {BoomDrillModal} from '../components/BoomDrillModal';
import {BoomBacktestPanel} from '../components/BoomBacktestPanel';
import {useBoomRadar} from '../hooks/useBoomRadar';
import {CATEGORY_LABELS} from './EarningsRadar.categories';
import './EarningsRadar.css';

export function EarningsRadar() {
  const [tab, setTab] = useState<'radar' | 'backtest'>('radar');

  return (
    <div className="er-page">
      <PageHeader title="财报雷达" subtitle="财报季 · 业绩大增 × 景气关键词 候选池" />
      <Tabs
        active={tab}
        onChange={(k) => setTab(k as typeof tab)}
        tabs={[
          {key: 'radar', label: '雷达'},
          {key: 'backtest', label: '策略验证'},
        ]}
      />
      {tab === 'radar' ? <RadarTab /> : <BoomBacktestPanel />}
    </div>
  );
}

/** 雷达 Tab:原页面主体(状态条 / 筛选 / 候选表 / 下钻 Modal)。 */
function RadarTab() {
  const [reportDate, setReportDate] = useState<string>('');
  const [activeCats, setActiveCats] = useState<Set<string>>(new Set());
  const [drill, setDrill] = useState<{symbol: string; reportDate: string} | null>(null);

  const params = useMemo(
    () => ({
      reportDate: reportDate || undefined,
      categories: activeCats.size ? Array.from(activeCats).join(',') : undefined,
    }),
    [reportDate, activeCats],
  );
  const {data, loading, error} = useBoomRadar(params);

  const toggleCat = (c: string) => {
    setActiveCats((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  };

  const season = data?.season;
  const rows = data?.candidates ?? [];

  return (
    <>
      <Card className="er-season">
        {loading && !data ? (
          <StateView state="loading" />
        ) : error ? (
          <StateView state="error" text={error} />
        ) : season ? (
          season.in_season ? (
            <div>
              <span className="er-season-badge er-season-badge--on">财报季</span>
              <b className="er-season-name">{season.window_name}</b>
              <span className="er-season-meta">
                {season.window_start} ~ {season.window_end} · 候选{' '}
                <b className="num">{data!.summary.pool}</b> 只 · 命中景气词{' '}
                <b className="num is-up">{data!.summary.with_hits}</b> 只
              </span>
            </div>
          ) : (
            <div>
              <span className="er-season-badge">休渔期</span>
              <span className="er-season-meta">
                下一预告窗 <b className="num">{season.next_window_start}</b> 开始,到时见
              </span>
            </div>
          )
        ) : null}
      </Card>

      <div className="er-controls">
        <select
          className="er-select"
          value={reportDate}
          onChange={(e) => setReportDate(e.target.value)}
        >
          <option value="">最新报告期</option>
          {(data?.report_dates ?? []).map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        {Object.entries(CATEGORY_LABELS).map(([code, label]) => (
          <button
            key={code}
            className={`er-cat ${activeCats.has(code) ? 'er-cat--on' : ''}`}
            onClick={() => toggleCat(code)}
          >
            {label}
          </button>
        ))}
      </div>

      {rows.length === 0 ? (
        <StateView state="empty" text="暂无候选(财报季每日 17:30 自动扫描)" />
      ) : (
        <table className="er-table">
          <thead>
            <tr>
              <th>代码</th><th>简称</th><th>类型</th>
              <th title="净利润同比(预告/单季)。低基数(上年同期极小)会把百分比放大到失真,结合绝对额看">业绩增幅</th>
              <th>景气信号</th><th>命中数</th><th>LLM</th><th>状态</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={`${c.symbol}-${c.report_date}`}
                  onClick={() => setDrill({symbol: c.symbol, reportDate: c.report_date})}>
                <td className="num er-sym">{c.symbol}</td>
                <td>{c.company_name ?? '-'}</td>
                <td>{c.forecast_type === 'express' ? '快报' : '预告'}</td>
                <td className={`num ${c.change_pct != null && c.change_pct >= 0 ? 'is-up' : 'is-down'}`}>
                  {c.change_pct != null ? `${c.change_pct > 0 ? '+' : ''}${c.change_pct.toFixed(1)}%` : '-'}
                </td>
                <td>
                  {c.category_labels?.length
                    ? c.category_labels.map((l) => (
                        <span className="er-tag" key={l}>{l}</span>
                      ))
                    : '-'}
                </td>
                <td className="num">{c.keyword_count}</td>
                <td className="num">
                  {c.llm_score != null ? `${c.llm_score}·${c.llm_verdict}` : '-'}
                </td>
                <td>{c.status === 'added_watchlist' ? '已入自选' : c.status}</td>
                <td>
                  <Button variant="secondary" size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDrill({symbol: c.symbol, reportDate: c.report_date});
                          }}>
                    详情
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {drill && (
        <BoomDrillModal
          symbol={drill.symbol}
          reportDate={drill.reportDate}
          onClose={() => setDrill(null)}
        />
      )}
    </>
  );
}
