# 论点条件历史回测（闭环增强）设计 spec

日期：2026-09-27
前置：1-7 期 + V2 已落地。本项来自体系完结后的候补方向①。

## 1. 目标

登记论点前/后校准假设条件阈值：给定条件集合，在过去 N 期（默认 16 季）
财报上逐期评估，输出每条条件的历史破位次数/频率/首次破位期——
破位率 100% 说明阈值不切实际，0% 且贴近现值说明阈值有效且有安全垫。

## 2. 口径与限制

- **支持**：全部财务类条件（roe / revenue_yoy / net_profit_yoy /
  gross_margin / ocf_ratio / debt_ratio），数据自
  `stock_financial_detail` 按 report_date GROUP BY 合并三表固定列；
  yoy 类用相邻前一期作基期（与线上装配同口径）。
- **不支持**：估值类条件（pe_ttm / pb / dv_ttm）需历史逐日估值序列，
  V1 标 `unknown` 并在输出 `valuation_unsupported` 提示
  "估值条件暂不支持历史回测"。

## 3. 纯函数（thesis_monitor.py 追加）

`backtest_conditions(conditions, periods) -> dict`：

- periods：升序 [{report_date(iso), revenue, net_profit_parent, ocf,
  total_assets, total_liabilities, equity, gross_margin}]
- 逐期（自第 2 期起，供 yoy 基期）：assemble=当期+前一期 →
  `compute_metric_values` → 每条条件 holding/breached/unknown
- summary（每条件）：`{metric_key, evaluated, breached, breach_rate,
  first_breach_report_date}`；输出另含
  `periods`（每期各条件状态）与 `valuation_unsupported` 列表

## 4. 服务与端点

- `service._backtest_periods(symbol, lookback=16)`：SQL GROUP BY 装配
  （模块级函数可 mock）。
- `POST /thesis/conditions-backtest` body `{symbol, conditions[],
  lookback?}` → 纯函数结果。注册在 /{thesis_id} 前。

## 5. 前端

- 登记对话框条件编辑器下：「校准阈值（16 季回测）」按钮 →
  每条条件显示 `破位 x/N（yy%）· 首破 YYYY-MM`；估值条件显示"不支持"。
- 详情页假设条件区：同样按钮与结果行。

## 6. 测试与验收

- 纯函数：合成 4 期序列（roe 递减触发破位；yoy 基期口径；
  估值 unknown；首破期；破位率）。
- 端点：mock `_backtest_periods`。
- 验收：两处入口可回测；后端测试 + 前端 build 通过。
