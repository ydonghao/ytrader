/**
 * Market page — 6 类分类查看 + 共享 KlineChart 蜡烛图
 * 分类: 大盘指数 / 行业指数 / 个股 / ETF / 商品货币 / 港股
 */
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { KlineChart } from '@ytrader/trading-market-data';
import { Card, CardContent, Tabs, TabList, Tab } from '@ytrader/common-components';
import { Button, PageHeader, StateView } from '../components/ui';
import { MarketAShare } from '../components/MarketPage';
import { getApiBase } from '../lib/api';
import './Market.css';

const API_BASE = getApiBase();

interface CategoryItem {
  symbol: string;
  name: string;
  close: number;
  change_pct: number;
}

type Categories = Record<string, CategoryItem[]>;

const TABS: { key: string; label: string; field: string }[] = [
  { key: 'market_index', label: '大盘指数', field: 'market_index' },
  { key: 'sw_index', label: '行业指数', field: 'sw_index' },
  { key: 'stock', label: '个股', field: 'stock' },
  { key: 'etf', label: 'ETF', field: 'etf' },
  { key: 'commodity_fx', label: '商品/货币', field: 'commodity_fx' },
  { key: 'hk', label: '港股', field: 'hk' },
];

// ETF 二级分类（按代码段前端过滤）
const ETF_FILTERS: { key: string; label: string; test: (s: string) => boolean }[] = [
  { key: 'all', label: '全部', test: () => true },
  { key: 'broad', label: '宽基', test: (s) => /^sh5(10|60)|^sz159(905|901|915|949)/.test(s) },
  { key: 'industry', label: '行业', test: (s) => /^sh5(12|15|16|17|88)|^sz159/.test(s) },
  { key: 'cross', label: '跨境', test: (s) => /^sh513/.test(s) },
  { key: 'gold', label: '黄金', test: (s) => /^sh518|^sz159(934|980)/.test(s) },
  { key: 'bond', label: '债券/货币', test: (s) => /^sh511|^sz159/.test(s) && !/^sh518/.test(s) },
];

// ── 分类列表（左侧）──────────────────────────────────────────────────────────

// 分类列表单次渲染上限：ETF/港股可达上千项，全量 .map 会卡顿。
const CATEGORY_RENDER_LIMIT = 200;

const CategoryList: React.FC<{
  items: CategoryItem[];
  selected: string;
  onSelect: (sym: string) => void;
  showEtfFilters?: boolean;
}> = ({ items, selected, onSelect, showEtfFilters }) => {
  const [query, setQuery] = useState('');
  const [etfFilter, setEtfFilter] = useState('all');

  // 过滤结果用 useMemo 缓存：港股/ETF 类目可达上千项，每次按键都全量过滤会卡顿。
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const flt = ETF_FILTERS.find((f) => f.key === etfFilter)!;
    return items.filter((it) => {
      const matchQ = !q || it.symbol.toLowerCase().includes(q) || it.name.toLowerCase().includes(q);
      const matchF = !showEtfFilters || flt.test(it.symbol);
      return matchQ && matchF;
    });
  }, [items, query, etfFilter, showEtfFilters]);
  const visible = filtered.slice(0, CATEGORY_RENDER_LIMIT);

  return (
    <div className="market-cat">
      <input
        className="market-cat__search"
        placeholder="搜索代码或名称..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {showEtfFilters && (
        <div className="market-cat__filters">
          {ETF_FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              className={`market-cat__chip ${etfFilter === f.key ? 'market-cat__chip--active' : ''}`}
              onClick={() => setEtfFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      )}
      <ul className="market-cat__list">
        {visible.map((it) => {
          const up = it.change_pct >= 0;
          return (
            <li key={it.symbol}>
              <button
                type="button"
                className={`market-cat__item ${selected === it.symbol ? 'market-cat__item--active' : ''}`}
                onClick={() => onSelect(it.symbol)}
              >
                <span className="market-cat__name">{it.name}</span>
                <span className="market-cat__code">{it.symbol}</span>
                <span className={`num market-cat__price ${up ? 'up' : 'down'}`}>
                  {it.close.toFixed(2)}
                  <span className="market-cat__pct">
                    {up ? '+' : ''}{it.change_pct.toFixed(2)}%
                  </span>
                </span>
              </button>
            </li>
          );
        })}
        {filtered.length > visible.length && (
          <li className="market-cat__empty">
            仅显示前 {visible.length} 项，共 {filtered.length} 项，请用搜索框缩小范围
          </li>
        )}
        {filtered.length === 0 && <li className="market-cat__empty">无数据</li>}
      </ul>
    </div>
  );
};

// ── Main Market Page ─────────────────────────────────────────────────────────

export const Market: React.FC = () => {
  const [activeTab, setActiveTab] = useState('market_index');
  const [categories, setCategories] = useState<Categories>({});
  // 按当前 Tab 的加载态：仅当前 Tab 首次拉取时显示 spinner，已加载的切回瞬间显示
  const [loadingCat, setLoadingCat] = useState<string | null>('market_index');
  const [selected, setSelected] = useState<string>('sh000001');
  // SPA 内跳转（window.location.href 会整页刷新、重拉全部 bundle 和状态）
  const navigate = useNavigate();

  // activeTab 的 ref：fetch 回填 selected 时确认用户仍停在该 Tab，避免切走后被劫持
  const activeTabRef = useRef(activeTab);
  useEffect(() => {
    activeTabRef.current = activeTab;
  }, [activeTab]);

  // 按分类懒加载：只取当前 Tab 的分类（?cat=），首屏只拉大盘指数
  const loadCategory = useCallback(async (cat: string) => {
    if (cat === 'stock') return; // 个股走前端搜索
    setLoadingCat(cat);
    try {
      const res = await fetch(`${API_BASE}/market/categories?cat=${cat}`);
      const json = await res.json();
      const items: CategoryItem[] = json.data?.[cat] || [];
      setCategories((prev) => ({ ...prev, [cat]: items }));
      // 仅当用户仍停在该 Tab 时选第一项
      if (activeTabRef.current === cat && items.length > 0) {
        setSelected(items[0].symbol);
      }
    } catch {
      setCategories((prev) => ({ ...prev, [cat]: [] }));
    } finally {
      setLoadingCat(null);
    }
  }, []);

  // 挂载时只拉默认 Tab（大盘指数 ~40ms），首屏极快
  useEffect(() => {
    loadCategory(activeTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentItems = categories[activeTab] || [];
  const isLoading = loadingCat === activeTab;

  // 切 Tab：已加载秒切并选第一项；未加载过则按需拉取
  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    if (tab === 'stock') return; // 个股 Tab 用 MarketAShare
    const items = categories[tab] || [];
    if (items.length > 0) {
      setSelected(items[0].symbol); // 已加载，秒切
    } else if (!(tab in categories)) {
      loadCategory(tab); // 首次切到，按需拉取
    }
  };

  return (
    <div className="market">
      <PageHeader title="行情" subtitle="分类行情 · 蜡烛图 · 实时数据" />

      <div className="market__tabs">
        <Tabs value={activeTab} onChange={(val) => handleTabChange(val as string)}>
          <TabList>
            {TABS.map((t) => (
              <Tab key={t.key} value={t.key}>{t.label}</Tab>
            ))}
          </TabList>
        </Tabs>
      </div>

      {activeTab === 'stock' ? (
        /* 个股 Tab: 复用现有 MarketAShare（自带搜索/RSI/量）*/
        <MarketAShare />
      ) : (
        <div className="market__content">
          <div className="market__left">
            <Card className="market__cat-card">
              <CardContent>
                {isLoading ? (
                  <StateView state="loading" text="加载分类数据中…" />
                ) : (
                  <CategoryList
                    items={currentItems}
                    selected={selected}
                    onSelect={setSelected}
                    showEtfFilters={activeTab === 'etf'}
                  />
                )}
              </CardContent>
            </Card>
          </div>
          <div className="market__right">
            <Card className="market__chart">
              <CardContent>
                {selected ? (
                  <>
                    <KlineChart symbol={selected} interval="1d" height={460} />
                    <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => navigate(`/financial?symbol=${selected}`)}
                      >
                        查看财务 →
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => navigate(`/valuation?symbol=${selected}`)}
                      >
                        估值分位 →
                      </Button>
                    </div>
                  </>
                ) : (
                  <StateView state="empty" text="请从左侧选择标的" />
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
};
