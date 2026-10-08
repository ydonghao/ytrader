# 仓位与安全边际（价值投资闭环第 4 期）设计 spec

日期：2026-09-27
状态：依据 2026-09-27-thesis-sell-system-design.md 附录路线执行
前置：1-3 期已落地（论点/卖出体检/重估/决策日志）

## 1. 目标

回答"该买多少"：给定质量分与安全边际，输出**透明可解释**的仓位建议
（档位区间为主、半凯利为参考、单票上限为硬约束）与三档分层建仓计划
（结构与 course_portfolio 的 entry_plan 对齐）。

非目标：不自动下单；不替代用户决策；不做相关性/行业上限（后续期）。

## 2. 模型（纯函数，新文件 fundamental/position_sizing.py）

`suggest_position_size(quality_score, safety_margin_pct, *,
downside_pct=25.0, kelly_fraction=0.5, single_cap_pct=20.0,
total_capital=None, current_price=None) -> dict`

全部中间量透出（同 quality_score 风格：可解释优先）：

1. **胜率估计** `p = clamp(0.40, 0.75, 0.45 + quality/100×0.15 +
   min(margin,40)/40×0.10)`——质量与低估各贡献一部分，上限压在 0.75
   （价值投资不假装能精确估计胜率）；
2. **赔率**：`upside_pct = margin/(100−margin)×100`（现价→公允）；
   下行风险取 `downside_pct`（默认 25% 风险预算）；
3. **凯利**：`kelly_full = max(0, p/(D) − (1−p)/(U))×100`；
   `kelly_half = kelly_full × kelly_fraction`——仅作参考值；
4. **档位（主建议）**：
   - 强：quality≥75 且 margin≥30 → 区间 15~20%
   - 中：quality≥60 且 margin≥15 → 区间 8~12%
   - 弱：其余 → 0~5%（或不买）
5. **综合**：`suggested_pct = min(clamp(band_low, band_high,
   kelly_half), single_cap_pct)`；kelly_half 为 0（无上行空间）→ 0；
6. **分层建仓**：仓位内按 40%/30%/30% 三档，价格档位 0%/−8%/−16%；
   提供 total_capital 与 current_price 时输出金额与股数（整百）。

缺数据（quality 或 margin 为 None）→ `data_missing=true`，
suggested_pct=null，UI 提示先补数据。

## 3. API

`GET /thesis/position-size/{symbol}?capital=1000000`：实时聚合
quality_report + DCF 公允价 + 最新收盘 → 模型输出。注册在
`/{thesis_id}` 之前。

## 4. 前端

Thesis 登记对话框：选定股票后自动拉取建议，展示紧凑卡片——
档位徽章（强/中/弱）、建议仓位 %（区间+综合值）、半凯利参考、
三档建仓表（价格档/仓位占比/金额）。数据缺失时显示提示。

## 5. 测试

- 纯函数：p 估计上下限、upside 换算、kelly 数学（含 0 与负）、
  档位边界（75/30、60/15 两侧）、cap 截断、ladder 结构与金额股数、
  缺数据路径。
- 端点：mock service 聚合函数，返回结构与 data_missing 两种。
- 回归：1-3 期测试不回退。

## 6. 验收

1. 登记对话框选股后显示建议仓位卡片，数值可解释（中间量齐全）。
2. 强档 example（quality 80/margin 30）与弱档（quality 50/margin 5）
   输出符合第 2 节规则。
3. 后端测试 + 前端 build 通过。
