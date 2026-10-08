# 温度计落库与回放（闭环增强）设计 spec

日期：2026-09-27
前置：温度计已上线（实时计算）；本项使其可回放：历史序列落库 +
登记论点时快照"买入时温度"，复盘时对照。

## 1. 目标

1. 每日 17:40 落一行温度快照；
2. **历史回填**：用指数估值×债券历史逐日重建全部历史温度
   （数据都在库里，一次回填即得 5~6 年温度序列）；
3. 论点 snapshot 增加 `thermometer` 块——买入时市场冷热留档；
4. 历史端点 + 温度卡可展开 ERP 曲线图。

## 2. 数据模型（1 张新表）

`market_thermometer_daily`：`trade_date(唯一), symbol, ep_pct, erp_pct,
level, level_label, position_low, position_high, erp_percentile,
buffett_pct, buffett_level, history_approx(bool)`。
UNIQUE(symbol, trade_date) 幂等；回填行 buffett 为 NULL
（全市场历史市值求和过重，不做）。

## 3. 服务（新文件 domain/market/thesis/thermometer_service.py）

- `compute_thermometer(symbol, gdp) -> dict`：自 thesis_handler.thermometer
  **原样抽出**（handler 改为薄包装），返回 dict。
- `sync_thermometer_daily()`：compute → upsert 当日行。
- `backfill_thermometer(symbol)`：pe_series × bond_series 逐日 →
  纯函数算每档 level/band + 运行分位 → 批量 upsert（可重跑）。
- `capture_snapshot` 追加 `thermometer` 块（compute 降级 None）。

## 4. 调度 + API

- job `thermometer_daily`：**17:40**（thesis_reeval 17:35 后）。
- `GET /thesis/thermometer/history?days=365&symbol=`：升序行。

## 5. 前端

- 温度卡新增"展开历史"：recharts 折线（erp_pct，按 level 着色带底色可
  后续迭代，V1 单线+当前点标注）。
- 论点详情页快照区显示"登记时温度：{level_label}（ERP x%）"对照当前卡。

## 6. 测试与验收

- repo：upsert 幂等/list 区间。
- 服务：compute mock 三源；backfill 用合成序列断言行数/level/运行分位。
- job 注册；快照含 thermometer 块。
- 验收：真实回填成功、历史端点有数据、温度卡可展开曲线；
  后端测试 + 前端 build 通过。
