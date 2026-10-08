# 全市场温度计（价值投资闭环第 7 期）设计 spec

日期：2026-09-27
状态：依据 thesis spec 附录路线执行（第 6 期管理层另排期，先做轻的 7）

## 1. 目标

给"当前整体仓位该多少"一个市场层面的锚：股债性价比（ERP）为主、
巴菲特指标为辅 → 五档温度 + 对应仓位水位建议。按需实时计算，
不落表不加 job（指数估值/宏观指标已有每日同步）。

## 2. 数据源（全部现成）

- 沪深300 PE(TTM) 及 5 年历史：`index_valuation_daily`
  （`get_index_range(source="computed")`，避开 legu 孤儿行）；
- 10Y 国债收益率：`macro_indicator.cn_bond_10y`（market_sentiment 已同步，
  值以 % 存储）；
- 全市场总市值：stock_valuation 每股最新 total_mv 求和（psycopg2 裸查）；
- GDP：默认假设 140 万亿元，query 参数可覆盖（输出中明示假设）。

## 3. 纯函数（新文件 fundamental/market_thermometer.py）

`market_thermometer(pe_ttm, bond_yield_pct, total_mv_sum=None,
gdp=None, erp_history=None) -> dict`

- `ep_pct = 100/pe`；`erp_pct = ep_pct − bond_yield_pct`；
- **五档**（A股经验阈值，2014/2018/2024 大底 ≈5.5%+，2015/2021 泡沫 <2.5%）：
  - ≥5.5 极冷 → 水位 80~90%；≥4.5 偏冷 → 70~80%；≥3.5 中性 → 50~60%；
    ≥2.5 偏热 → 30~40%；<2.5 过热 → 20~30%
- `erp_percentile`：当前 ERP 在历史序列中的分位（有历史才输出）；
  V1 历史序列用"历史 E/P − 当前国债"近似（PE 周期主导，注明）；
- 巴菲特指标 `total_mv_sum/gdp×100`：<70 低估 / 70~90 合理 /
  90~110 偏高 / ≥110 泡沫（仅参考，不驱动水位）；
- 任一输入缺失对应字段置 None，不阻塞其余计算。

## 4. API + 前端

- `GET /thesis/thermometer?gdp=140&symbol=sh000300`
- 持仓体检主页顶部温度卡片：档位徽章（按档着色）+ ERP/分位 +
  巴菲特指标 + 建议仓位水位。

## 5. 测试与验收

- 纯函数：五档边界、E/P 换算、分位、巴菲特档位、缺输入路径。
- 端点：mock 数据源三态（全齐/缺债/缺市值）。
- 验收：主页显示温度卡；后端测试与前端 build 通过。
