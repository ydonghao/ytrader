# 价值投资三期设计 spec（决策质量层）

日期：2026-09-27
定位：核心闭环完成后的决策质量层——买入假设的对照（G1）、卖出决策的反馈（G2）、
择时建议的自检（G3）、尾部风险（G4）、覆盖流程（G5）。

## G1 Reverse DCF——市场隐含预期

- 纯函数 `reverse_dcf.py`：`implied_terminal_growth(latest_fcf, mv,
  wacc, growth_rate, years)`——二分求 g 使 dcf_intrinsic_value=市值
  （g∈[-0.10, wacc-0.005]，单调）；附带 `fcf_yield = fcf/mv`。
  不可达/越界 → 明确输出（"隐含预期超出合理区间"）。
- `GET /financial/reverse-dcf/{symbol}?wacc=&growth_rate=`：
  输出隐含永续增长、FCF 收益率、与估值中心当前假设的对照。
- 前端：ValuationHub 总览加"市场隐含预期"卡。

## G2 卖出后评估——决策反馈环

- 纯函数（thesis_monitor）：`closed_performance(closed_theses, prices)`
  → 每条 {symbol, closed_at, close_price, current_price,
  since_close_pct} + 汇总（均值/中位、卖飞比例）。
- `GET /thesis/closed-performance`；复盘区"关闭后表现"列 +
  汇总行（"关闭后平均 +x% / 卖飞 y/z"）。

## G3 温度计水位策略回测——吃自己的狗粮

- 数据：`market_thermometer_daily`（若 cn_bond_10y 表内历史>1500 行
  则先扩回填窗口）+ index_ohlcv(sh000300)。
- 纯函数（market_thermometer）：`allocation_backtest(thermo_rows,
  index_rows, rebalance_days=21, cash_annual=0.02)`——按五档水位
  中值调仓（极冷90%…过热25%），对比买入持有：CAGR/最大回撤/调仓次数。
- `GET /thesis/thermometer/backtest`；温度卡展开处加结果行。

## G4 组合压力测试

- 场景窗（sh000300 历史极值段）：2018 贸易战 / 2020 疫情 /
  2021-2024 长熊 / 2024-01 流动性冲击——窗内指数跌幅由 index_ohlcv
  实算，不硬编码。
- 纯函数 `stress_test(positions, scenarios)`：各持仓用**自身**窗内
  跌幅（历史不足的用指数跌幅×1.0 并标注）；输出组合跌幅与最大拖累。
- `GET /thesis/stress-test`；组合体检区加小节。

## G5 研究管道（漏斗）

- **零新表**：阶段从现有数据推导——已持仓(active thesis) > 已关闭 >
  已体检(stock_checklist_item 近90天有更新) > 已研究(research_note)
  > 观察(watchlist)。
- 纯函数 `pipeline_stages(watchlist_syms, checked_syms, noted_syms,
  active_syms, closed_syms)` → 分层列表 + 滞留提醒
  （已体检>14天未做决定）。
- `GET /thesis/pipeline`；持仓体检页折叠区。

## 通用

TDD、每功能独立 commit、真实数据验证（茅台/G5 用真实库）；
无新表（G1-G5 全部只读或复用现有表）。
