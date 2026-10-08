import React, {useMemo, useState} from 'react';
import {Link} from 'react-router-dom';
import {PageHeader} from '../components/ui';
import {
  navGroups,
  scenarios,
  workflowStages,
  CALIBRATION_NOTES,
} from '../config/navigation';
import './Start.css';

const pathLabel = new Map(
  navGroups.flatMap((g) => g.items.map((i) => [i.path, i.label] as [string, string]))
);

export const Start: React.FC = () => {
  const [query, setQuery] = useState('');

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return navGroups;
    return navGroups
      .map((g) => ({
        ...g,
        items: g.items.filter((i) =>
          [i.label, i.desc, ...(i.aliases ?? [])].join(' ').toLowerCase().includes(q)
        ),
      }))
      .filter((g) => g.items.length > 0);
  }, [query]);

  return (
    <div className="start-page">
      <PageHeader
        title="开始"
        subtitle="A股价值投资工作台:从判断市场贵贱到卖出复盘的完整闭环"
      />

      {/* ── 工作流地图 ── */}
      <section>
        <h2 className="start-section-title">投资闭环:六步走完一圈</h2>
        <div className="start-workflow">
          {workflowStages.map((stage) => (
            <div key={stage.id} className="start-stage">
              <span className="start-stage__title">{stage.title}</span>
              <span className="start-stage__role">{stage.role}</span>
              <div className="start-stage__links">
                {stage.links.map((link) => (
                  <Link key={link.path + link.label} to={link.path}>
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── 场景卡 ── */}
      <section>
        <h2 className="start-section-title">按你想做的事找功能</h2>
        <div className="start-scenarios">
          {scenarios.map((s) => (
            <div key={s.id} className="start-scenario">
              <span className="start-scenario__question">{s.question}</span>
              <span className="start-scenario__answer">{s.answer}</span>
              <div className="start-scenario__links">
                <Link className="start-scenario__primary" to={s.primary}>
                  {pathLabel.get(s.primary) ?? s.primary} →
                </Link>
                {s.links.map((link) => (
                  <Link key={link.path} className="start-scenario__secondary" to={link.path}>
                    {link.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── 页面速查表 ── */}
      <section>
        <h2 className="start-section-title">页面速查</h2>
        <input
          className="start-filter"
          aria-label="搜索页面"
          placeholder="搜功能:估值 / 排雷 / 回测 / 温度…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="start-cheatsheet">
          {filteredGroups.map((g) => (
            <div key={g.id} className="start-cheatsheet-group">
              <h3>{g.title}</h3>
              <table className="start-cheatsheet-table">
                <tbody>
                  {g.items.map((i) => (
                    <tr key={i.path}>
                      <td>
                        <Link to={i.path}>{i.label}</Link>
                      </td>
                      <td className="start-cheatsheet-desc">{i.desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {filteredGroups.length === 0 && (
            <p className="start-cheatsheet-desc">没有匹配的页面,换个关键词试试。</p>
          )}
        </div>
      </section>

      {/* ── 口径速记 ── */}
      <details className="start-calibration">
        <summary>口径速记(防误读)</summary>
        <ul>
          {CALIBRATION_NOTES.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </details>
    </div>
  );
};
