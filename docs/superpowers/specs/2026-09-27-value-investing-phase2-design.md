# 价值投资二期工程设计 spec（组合维度 + 决策质量）

日期：2026-09-27
前置：一期闭环（论点/卖出体检/重估/日志/仓位/排雷/温度计/资本配置）已落地并联调。
定位：单标的闭环完成后的下一层——组合维度（F1/F4/F5）与决策质量工具（F2/F3/F6/F7）。

## F1 组合风险管理（`GET /thesis/portfolio-risk`）

active 论点为持仓。纯函数 `fundamental/portfolio_risk.py`：

- `industry_concentration(positions)`：按申万 L1 分组权重；
  行业 >40% → flag（数据源：industry_analysis repo 成分映射，
  查不到行业的归"未知"）。
- `correlation_matrix(returns)`：过去 250 交易日日收益 pearson 两两矩阵
  + 有效独立仓位数 N_eff=(Σw)²/Σ(w·C·w)（相关系数加权）。
- `portfolio_valuation(positions_metrics)`：市值加权 PE/PB，
  对照全市场（指数估值 computed 口径）。
- `concentration_flags` 输出人话列表。
前端：持仓体检页"组合体检"折叠区（行业表/相关性热表/加权估值对照）。
假设声明：权重=个股市值/持仓总市值（不含现金，注明）。

## F2 候选对比工作台（`GET /thesis/compare?symbols=`，≤4 只）

聚合现成维度，无新计算：质量分/verdict、五法 upside、TTM ROE、
营收同比、护城河分、资本配置分、排雷等级、PE/PB/股息率。
前端：新页 `/compare`（菜单"标的对比"）：StockSearch 添加 2~4 只 →
对比表（列=标的，行=维度，最优值高亮）。Financial 页加"对比"深链。

## F3 估值补齐（financial router）

- **DCF 敏感性**：`GET /financial/dcf/{symbol}/sensitivity`
  → WACC(默认 8~12% 步1%)×永续增长(1~5% 步1%) 网格的内在值/股，
  每格标注 >/< 现价；纯函数网格（复用 dcf 域函数），handler 取数。
- **综合公允区间**：`GET /financial/fair-range/{symbol}`
  → 五法 upside→公允/现价比，取中位数与 min/max 为区间，
  输出现价(=1.0)位置与"低估/合理/高估"。
  纯函数 `fair_value_range(upside_dict)`。
前端：ValuationHub 加敏感性表（配色标注）与公允区间条。

## F4 股息现金流（`GET /thesis/dividend-calendar`）

active 论点持仓：纯函数 `dividend_projection(dividends, shares, today)`：

- 近 5 年每年每股分红合计 + 年增速；
- 未来 12 月投影：每股年分红按历史除息月份分布排期，
  金额=每股分红×股数；输出月度收入流与年合计。
前端：持仓体检页"股息日历"折叠区（月度表+年预期+增长史）。

## F5 建仓执行跟踪

- `investment_thesis` 加 `entry_ladder JSON`（登记时可选保存三档计划）；
- 新表 `thesis_ladder_fill`（thesis_id FK, rung_index, price, shares,
  filled_at）；`POST /thesis/{id}/ladder-fills`、删除；
- 详情页 ladder 表每档"标记成交"（价格默认档位价）；
  汇总已投/计划比、均价。纯函数 `ladder_progress(ladder, fills)`。

## F6 研究笔记

- 新表 `research_note`（symbol indexed, title, content, created/updated）；
- CRUD：`GET/POST /thesis/notes?symbol=`、`PUT/DELETE /thesis/notes/{id}`；
- 前端：轻页 `/notes`（StockSearch 过滤+编辑器），Financial 页"笔记"深链。
  论点详情显示该标的研究笔记列表（只读+跳转）。

## F7 选股器历史评分前视修复

排查 screener 历史评分路径是否绕过 point-in-time（snapshot 的
as_of+lag_days）；修复为强制 as_of 截断 + 回归测试。

## 通用约束

- 全部沿用既有模式：SQLModel+create_all、纯函数+handler、TDD、
  每功能独立 commit；金融数值一律真实公司 sanity check。
- F1/F4 前端折叠区进持仓体检页；新路由菜单项 ≤2 个（对比/笔记）。

## 验收（逐项）

各功能端点+UI 可用；二期全量回归过；茅台/组合真实数据 sanity。
