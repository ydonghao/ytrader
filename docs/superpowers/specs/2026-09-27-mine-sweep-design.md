# 排雷筛选器（价值投资闭环第 5 期）设计 spec

日期：2026-09-27
状态：依据 2026-09-27-thesis-sell-system-design.md 附录路线执行
前置：1-4 期已落地。z/m/fraud 三信号已存在于
`classic_models.py`（纯函数）与 `financial_detail_handler`（单标的报告）。

## 1. 目标

把散在买入体检里的排雷信号抽成独立体系：
**持仓精查**（Z+M+红旗三查，每日）与**全市场 Z 扫描**（每周批量），
高危结果落库成排雷名单，并给持仓论点发 `mine_detected` 事件。

非目标：不做 M 的全市场扫描（需两期 detail 科目，成本高收益低）；
不替代买入体检（那边继续展示明细）。

## 2. 纯函数（新文件 fundamental/mine_sweep.py）

`assess_mine(z_verdict, m_verdict, fraud_severity) -> dict`：

- **high**：z=distress 或 m=manipulator 或 fraud=high_risk（任一）
- **medium**：z=grey 或 m=watch 或 fraud=watch
- 其余 **clean**；`reasons` 列出触发项（人话）
- 任一输入 None → 该源不参与判定（reasons 标注"数据缺失"不触发）

## 3. 数据模型（1 张新表）

`mine_screening_result`：`symbol(index), report_date, z, z_verdict,
m, m_verdict, m_partial, fraud_severity, fraud_flags JSON,
risk_level(high/medium/clean), source(positions/market), scanned_at`，
UNIQUE(symbol, report_date) 幂等 upsert。

## 4. 服务（新文件 domain/market/thesis/mine_sweep.py）

- `check_positions()`：active 论点逐标的调 z/m/fraud 三个 handler
  （`_data()` 降级模式，模块级包装函数便于 mock）→ assess →
  upsert(source=positions)；**risk=high 且该 report_date 未告警过** →
  `thesis_event(kind=mine_detected, detail={risk, reasons, report_date})`。
- `scan_market()`：`fetch_financial_snapshot(全市场, include_detail=False)`
  + 最新市值（repo 新方法 `latest_market_caps`）批量算 Altman Z →
  upsert(source=market，仅 z 字段)。
- 挂钩：`run_daily()` 末尾调 `check_positions()`（函数内延迟 import 防环）。

## 5. Repository 新方法

`upsert_mine_result / list_mines(level, limit)（high 优先、时间倒序）/
latest_market_caps(symbols)（stock_valuation 最新 total_mv）/
all_financial_symbols()（stock_financial_detail DISTINCT symbol）`。

## 6. API + 调度

- `GET /thesis/mines?level=&limit=`（注册在 /{thesis_id} 前）
- `POST /thesis/mines/scan` body `{scope: positions|market}` 手动触发
- job `mine_market_scan`：**周六 06:00**（financial_full_weekly Sat 05:00 后）

## 7. 前端

Thesis 主页新增"排雷雷达"折叠区：高危/观察名单表
（symbol/z/z_verdict/m/m_verdict/fraud/理由/财报期）+ 两个手动扫描按钮
（持仓精查/全市场Z扫描）。预警中心 kind 标签补 `mine_detected`。

## 8. 测试

assess_mine 组合矩阵；repo upsert 幂等与排序；check_positions mock
三源（high 触发事件、二次运行不重复、None 源跳过）；端点列表；
回归 1-4 期。

## 9. 验收

1. 手动"持仓精查"对 active 论点产出三源结果，高危落事件且可重跑不重复。
2. 全市场扫描产出 Z 名单（distress/grey），落库可查。
3. 周六 06:00 job 注册成功；预警中心显示排雷告警。
4. 后端测试 + 前端 build 通过。
