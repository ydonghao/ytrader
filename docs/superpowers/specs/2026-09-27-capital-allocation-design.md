# 管理层与资本配置（价值投资闭环第 6 期）设计 spec

日期：2026-09-27
数据探查结论：stock_dividend（事件级分红史）/ stock_shareholder_count（户数史）/
derived_metrics.roic / stock_valuation(dv_ttm,pe_ttm) 全部现成；
akshare provider 无增减持/回购接口——**V1 用现有数据**，
增减持/回购同步链路列为 follow-up（接口候选 stock_repurchase_em /
股东持股变动类，需联网验证后另立 spec）。

## 1. 目标

对持仓/候选股回答"管理层是否善待股东、资本配置是否理性"：
分红连续性与意愿、分红率合理性、ROIC 水平、筹码集中度变化 →
四维报告 + verdict（shareholder_friendly / neutral / concerning）。

## 2. 纯函数（新文件 fundamental/capital_allocation.py）

`capital_allocation(dividend_years, payout_pct, roic_pct,
holder_change_pct) -> dict`（输入均可 None=数据缺失不判定）：

- **分红维度**：dividend_years=近 N 年每年是否分红的 bool 列表
  （升序）→ 连续分红年数（自最近一年往前数）、是否铁公鸡
  （≥8 年数据且全 0）；连续≥5 → 加分项，铁公鸡 → 减分项
  （但 payout/ROIC 高的成长股可对冲，见 verdict 规则）；
- **分红率**：`payout = dv_ttm × pe_ttm / 100`（两率相除法，无需股本）；
  合理区 20~70% 加分；<10% 且非高 ROIC（≥12%）→ 铁公鸡 flag；
  >90% → 不可持续 flag；
- **ROIC**（derived_metrics.roic，%）：≥12 优秀加分；≥8 合格；
  <6 → 再投资毁灭价值 flag（分红率低+ROIC<6 = 最差组合）；
- **筹码**（弱信号仅参考）：股东户数同比下降>10% → 集中 +；
  升>30% → 分散 −；
- **score 0~100** 透明加权（分红30 + 分红率20 + ROIC35 + 筹码15，
  缺失维度按剩余权重归一）；verdict：score≥70 friendly /
  45~70 neutral / <45 concerning；硬规则：铁公鸡+ROIC<6 →
  直接 concerning。

## 3. API + 前端

- `GET /thesis/capital-allocation/{symbol}`（注册在 /{thesis_id} 前）：
  聚合四源（dividend repo / valuation / snapshot→roic / shareholder repo）；
- Thesis 详情页新增"管理层与资本配置"区块：score、verdict 徽章、
  四维明细（含"缺数据"态）。

## 4. 测试与验收

- 纯函数：连续年数统计、铁公鸡、payout 三区、ROIC 三档、
  归一化计分、硬规则、缺输入降级。
- 端点：mock 四源全齐/部分缺失两态。
- 验收：详情页显示报告；后端测试 + 前端 build 通过。
