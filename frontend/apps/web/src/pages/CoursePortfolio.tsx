/**
 * 自动建组合(课程组合): 风险偏好配比 → 生成预览 → 落库 → 周检视闭环。
 * 课程23: 红利/蓝筹/创新三类配比; 课程24: PE估值带档位+层层狙击+周检视。
 */
import {useCallback, useEffect, useState} from 'react';
import {Link} from 'react-router-dom';
import './CoursePortfolio.css';
import {
  api,
  CATEGORY_LABEL,
  categoryOf,
  fmtMoney,
  fmtPct,
  PE_STATE_LABEL,
  PE_STATE_TONE,
  RISK_PROFILES,
  type Category,
  type DetailLeg,
  type GenerateResponse,
  type PlanDetail,
  type PlanLeg,
  type PlanSummary,
  type ReviewResponse,
  type RiskProfile,
  validateWizardInput,
} from '../lib/coursePortfolio';

type View = 'list' | 'wizard' | 'detail';

const STATUS_LABEL: Record<string, string> = {
  planned: '待建仓', building: '建仓中', complete: '已建成',
};

const ADVICE_LABEL: Record<string, string> = {
  BUY_RUNG: '买入触发', TRIM: '超配减仓', BREAKDOWN: '破位复查', HOLD: '持有',
};

export default function CoursePortfolio() {
  const [view, setView] = useState<View>('list');
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [detail, setDetail] = useState<PlanDetail | null>(null);
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [error, setError] = useState('');

  const loadPlans = useCallback(async () => {
    try {
      setPlans(await api<PlanSummary[]>(''));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    if (view === 'list') {
      loadPlans();
    }
  }, [view, loadPlans]);

  const openDetail = useCallback(async (id: number) => {
    try {
      setError('');
      const [d, r] = await Promise.all([
        api<PlanDetail>(`/${id}`),
        api<ReviewResponse>(`/${id}/review`),
      ]);
      setDetail(d);
      setReview(r);
      setView('detail');
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const refreshDetail = useCallback(async (id: number) => {
    const [d, r] = await Promise.all([
      api<PlanDetail>(`/${id}`),
      api<ReviewResponse>(`/${id}/review`),
    ]);
    setDetail(d);
    setReview(r);
  }, []);

  return (
    <div className="page course-portfolio">
      <div className="page-header">
        <div>
          <h1>自动建组合</h1>
          <p className="page-subtitle">
            风险偏好配比(课程23)× PE估值带分批建仓(课程24):红利/蓝筹/创新,预留10%现金,层层狙击,周检视
          </p>
        </div>
        <div className="cp-actions">
          {view === 'list' && (
            <button className="cp-btn cp-btn--primary" onClick={() => setView('wizard')}>
              + 新建组合
            </button>
          )}
          {view !== 'list' && (
            <button className="cp-btn cp-btn--ghost" onClick={() => setView('list')}>
              ← 返回列表
            </button>
          )}
        </div>
      </div>
      {error && <div className="cp-error">{error}</div>}
      {view === 'list' && (
        <PlanList plans={plans} onOpen={openDetail} onDeleted={loadPlans} />
      )}
      {view === 'wizard' && (
        <Wizard
          onSaved={async (id) => {
            setView('list');
            await openDetail(id);
          }}
        />
      )}
      {view === 'detail' && detail && (
        <PlanDetailView
          detail={detail}
          review={review}
          onChanged={() => refreshDetail(detail.id)}
        />
      )}
    </div>
  );
}

function PlanList(props: {
  plans: PlanSummary[];
  onOpen: (id: number) => void;
  onDeleted: () => void;
}) {
  const {plans, onOpen, onDeleted} = props;
  const del = async (id: number) => {
    if (!window.confirm('确认删除该组合计划?')) {
      return;
    }
    try {
      await api(`/${id}`, {method: 'DELETE'});
      onDeleted();
    } catch (e) {
      /* 列表页静默, 刷新即可 */
      onDeleted();
    }
  };
  if (!plans.length) {
    return <div className="cp-empty">还没有组合计划, 点右上角"新建组合"开始。</div>;
  }
  return (
    <table className="cp-table">
      <thead>
        <tr>
          <th>名称</th><th>风险偏好</th><th>资金</th><th>股票数</th>
          <th>状态</th><th>创建时间</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        {plans.map((p) => (
          <tr key={p.id}>
            <td>
              <a onClick={() => onOpen(p.id)} className="cp-link">{p.name}</a>
            </td>
            <td>
              {RISK_PROFILES.find((r) => r.key === p.risk_profile)?.label ?? p.risk_profile}
            </td>
            <td>{fmtMoney(p.total_capital)}</td>
            <td>{p.target_stock_count}</td>
            <td>
              <span className={`cp-badge cp-badge--${p.status}`}>
                {STATUS_LABEL[p.status] ?? p.status}
              </span>
            </td>
            <td>{p.created_at?.slice(0, 10) ?? '—'}</td>
            <td>
              <button className="cp-btn cp-btn--ghost cp-btn--sm" onClick={() => del(p.id)}>
                删除
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Wizard(props: {onSaved: (id: number) => void}) {
  const {onSaved} = props;
  const [step, setStep] = useState<1 | 2>(1);
  const [profile, setProfile] = useState<RiskProfile['key']>('balanced');
  const [capital, setCapital] = useState(500000);
  const [stockCount, setStockCount] = useState(8);
  const [gen, setGen] = useState<GenerateResponse | null>(null);
  const [legs, setLegs] = useState<PlanLeg[]>([]);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const generate = async () => {
    // 输入框清空/误输入会让 state 变成 0/NaN, 后端只回笼统的
    // "参数验证失败", 必须在提交前拦下并给出具体提示
    const problem = validateWizardInput(capital, stockCount);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const data = await api<GenerateResponse>('/generate', {
        method: 'POST',
        body: JSON.stringify({
          total_capital: capital,
          risk_profile: profile,
          stock_count: stockCount,
        }),
      });
      setGen(data);
      setLegs(data.legs);
      setStep(2);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const swapLeg = (cat: Category, symbol: string, idx: number) => {
    const cand = gen?.candidates?.[cat]?.find((c) => c.symbol === symbol);
    if (!cand) {
      return;
    }
    setLegs((prev) => prev.map((l, i) => (
      i === idx ? {
        ...l,
        symbol: cand.symbol,
        name: cand.symbol,
        pe_band: null,
        entry_plan: [],
      } : l
    )));
  };

  const save = async () => {
    const problem = validateWizardInput(capital, stockCount);
    if (problem) {
      setError(problem);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const {id} = await api<{id: number}>('', {
        method: 'POST',
        body: JSON.stringify({
          name: name || undefined,
          total_capital: capital,
          risk_profile: profile,
          stock_count: stockCount,
          legs: legs.map((l) => ({
            symbol: l.symbol,
            category: l.category,
            target_weight: l.target_weight,
            target_amount: l.target_amount,
          })),
        }),
      });
      onSaved(id);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  if (step === 1) {
    return (
      <div className="cp-wizard">
        <h2>第一步 · 风险偏好与资金</h2>
        <div className="cp-profiles">
          {RISK_PROFILES.map((p) => (
            <button
              key={p.key}
              className={`cp-profile-card${profile === p.key ? ' is-active' : ''}`}
              onClick={() => setProfile(p.key)}
            >
              <div className="cp-profile-name">{p.label}</div>
              <div className="cp-profile-desc">{p.desc}</div>
              <div className="cp-profile-weights">
                红{Math.round(p.weights.dividend * 100)}% ·
                {' '}蓝{Math.round(p.weights.bluechip * 100)}% ·
                {' '}创{Math.round(p.weights.growth * 100)}%
              </div>
            </button>
          ))}
        </div>
        <div className="cp-form-row">
          <label>总资金(元)
            <input type="number" value={capital} min={10000} step={10000}
              onChange={(e) => setCapital(Number(e.target.value))} />
          </label>
          <label>股票数量(5–8, 课程24建议8)
            <input type="number" value={stockCount} min={5} max={8}
              onChange={(e) => setStockCount(Number(e.target.value))} />
          </label>
          <label>组合名称(可选)
            <input type="text" value={name} placeholder="留空自动命名"
              onChange={(e) => setName(e.target.value)} />
          </label>
        </div>
        {error && <div className="cp-error">{error}</div>}
        <button className="cp-btn cp-btn--primary" disabled={busy} onClick={generate}>
          {busy ? '生成中…' : '生成组合预览'}
        </button>
      </div>
    );
  }

  const cats: Category[] = ['dividend', 'bluechip', 'growth'];
  return (
    <div className="cp-wizard">
      <h2>第二步 · 预览并保存</h2>
      {gen && (
        <div className="cp-summary">
          可投资金 {fmtMoney(gen.investable_capital)}(预留10%现金)
          · 配额 {cats.map((c) => `${CATEGORY_LABEL[c]} ${gen.slots[c] ?? 0}`).join(' / ')}
        </div>
      )}
      {gen?.warnings.map((w, i) => (
        <div key={i} className="cp-warning">{w}</div>
      ))}
      {cats.map((cat) => {
        const group = legs.filter((l) => l.category === cat);
        if (!group.length) {
          return null;
        }
        return (
          <section key={cat} className="cp-cat">
            <h3>{CATEGORY_LABEL[cat]}</h3>
            <table className="cp-table">
              <thead>
                <tr>
                  <th>标的</th><th>目标权重</th><th>目标金额</th>
                  <th>估值状态</th><th>建仓档位</th><th>换股</th>
                </tr>
              </thead>
              <tbody>
                {group.map((l) => {
                  const idx = legs.indexOf(l);
                  return (
                    <tr key={l.symbol}>
                      <td>{l.name}({l.symbol})</td>
                      <td>{fmtPct(l.target_weight)}</td>
                      <td>{fmtMoney(l.target_amount)}</td>
                      <td>
                        {l.pe_band && (
                          <span className={`cp-badge cp-tone--${PE_STATE_TONE[l.pe_band.state] ?? 'muted'}`}>
                            {PE_STATE_LABEL[l.pe_band.state] ?? l.pe_band.state}
                          </span>
                        )}
                      </td>
                      <td><RungsCell rungs={l.entry_plan} /></td>
                      <td>
                        <select
                          value=""
                          onChange={(e) => swapLeg(cat, e.target.value, idx)}
                        >
                          <option value="">换成…</option>
                          {(gen?.candidates?.[cat] ?? []).map((c) => (
                            <option key={c.symbol} value={c.symbol}>
                              {c.symbol} 股息{c.dv_ttm != null ? c.dv_ttm.toFixed(1) : '—'}%
                            </option>
                          ))}
                        </select>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        );
      })}
      {error && <div className="cp-error">{error}</div>}
      <div className="cp-actions">
        <button className="cp-btn cp-btn--ghost" onClick={() => setStep(1)}>← 上一步</button>
        <button className="cp-btn cp-btn--primary" disabled={busy || !legs.length} onClick={save}>
          {busy ? '保存中…' : '确认落库'}
        </button>
      </div>
    </div>
  );
}

function RungsCell(props: {
  rungs: {rung_index: number; price_level: number; amount: number; executed?: boolean}[];
}) {
  const {rungs} = props;
  if (!rungs?.length) {
    return <span className="cp-muted">无档位(等待/数据不足)</span>;
  }
  return (
    <span className="cp-rungs">
      {rungs.map((r) => (
        <span key={r.rung_index} className={`cp-rung${r.executed ? ' is-done' : ''}`}>
          {r.rung_index === 0 ? '底' : `+${r.rung_index}`}
          @{r.price_level.toFixed(2)}
        </span>
      ))}
    </span>
  );
}

function PlanDetailView(props: {
  detail: PlanDetail;
  review: ReviewResponse | null;
  onChanged: () => void;
}) {
  const {detail, review, onChanged} = props;
  const [filling, setFilling] = useState<{leg: DetailLeg; rungIndex: number} | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const doFill = async (price?: number) => {
    if (!filling) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api(`/${detail.id}/legs/${filling.leg.id}/fills`, {
        method: 'POST',
        body: JSON.stringify({rung_index: filling.rungIndex, fill_price: price}),
      });
      setFilling(null);
      onChanged();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const adviceBySymbol = new Map((review?.advices ?? []).map((a) => [a.symbol, a]));
  const activeAdvices = (review?.advices ?? []).filter((a) => a.code !== 'HOLD');

  return (
    <div className="cp-detail">
      <div className="cp-summary">
        {detail.name} · {STATUS_LABEL[detail.status] ?? detail.status}
        · 总资金 {fmtMoney(detail.total_capital)}
        · 已投入 {fmtMoney(review?.progress_invested)}
        / 目标 {fmtMoney(review?.progress_target)}
        · 可用现金 {fmtMoney(review?.cash_remaining)}
        {review?.dividend_yield_weighted != null &&
          ` · 组合股息率 ${review.dividend_yield_weighted.toFixed(2)}%`}
      </div>
      {error && <div className="cp-error">{error}</div>}
      {activeAdvices.length ? (
        <div className="cp-advices">
          {activeAdvices.map((a) => (
            <div key={a.symbol} className={`cp-advice cp-advice--${a.code}`}>
              <b>{ADVICE_LABEL[a.code] ?? a.code}</b> · {a.symbol} {a.message}
            </div>
          ))}
        </div>
      ) : (
        <div className="cp-empty">本周无触发项, 按兵不动(课程24: 拒绝盘中临时起意)。</div>
      )}
      <table className="cp-table">
        <thead>
          <tr>
            <th>标的</th><th>类别</th><th>权重</th><th>进度</th>
            <th>成本/已投入</th><th>档位</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {detail.legs.map((l) => {
            const done = l.entry_plan.filter((r) => r.executed).length;
            const total = l.entry_plan.length;
            return (
              <tr key={l.id}>
                <td>{l.name}({l.symbol})</td>
                <td>{CATEGORY_LABEL[categoryOf(l.category)]}</td>
                <td>{fmtPct(l.target_weight)}</td>
                <td>{total ? `${done}/${total}档` : '观察'}</td>
                <td>
                  {l.shares > 0
                    ? `${l.avg_cost.toFixed(2)} / ${fmtMoney(l.invested_amount)}`
                    : '—'}
                </td>
                <td><RungsCell rungs={l.entry_plan} /></td>
                <td>
                  {l.shares > 0 && (
                    <Link
                      to={`/thesis?symbol=${l.symbol}&buy_price=${l.avg_cost}&shares=${l.shares}`}
                      className="cp-btn cp-btn--ghost cp-btn--sm cp-thesis-link"
                      title="把这条持仓登记为投资论点（带入成本/股数）">
                      论点
                    </Link>
                  )}
                  {l.entry_plan.filter((r) => !r.executed).map((r) => (
                    <button key={r.rung_index} className="cp-btn cp-btn--ghost cp-btn--sm"
                      onClick={() => setFilling({leg: l, rungIndex: r.rung_index})}>
                      标记买{r.rung_index === 0 ? '底仓' : `第${r.rung_index + 1}档`}
                    </button>
                  ))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {filling && (
        <div className="cp-modal-mask" onClick={() => setFilling(null)}>
          <div className="cp-modal" onClick={(e) => e.stopPropagation()}>
            <h3>标记成交</h3>
            <p>
              {filling.leg.symbol} 第{filling.rungIndex + 1}档
              · 计划金额 {fmtMoney(filling.leg.entry_plan[filling.rungIndex]?.amount)}
            </p>
            <p className="cp-muted">不填价格将按最新收盘价折算整手股数。</p>
            <FillForm onSubmit={doFill} busy={busy} onCancel={() => setFilling(null)} />
          </div>
        </div>
      )}
    </div>
  );
}

function FillForm(props: {
  onSubmit: (price?: number) => void;
  busy: boolean;
  onCancel: () => void;
}) {
  const [price, setPrice] = useState('');
  return (
    <div className="cp-form-row">
      <label>成交价(可选)
        <input type="number" step={0.01} min={0} value={price}
          onChange={(e) => setPrice(e.target.value)} />
      </label>
      <button className="cp-btn cp-btn--primary" disabled={props.busy}
        onClick={() => props.onSubmit(price ? Number(price) : undefined)}>
        确认
      </button>
      <button className="cp-btn cp-btn--ghost" onClick={props.onCancel}>取消</button>
    </div>
  );
}
