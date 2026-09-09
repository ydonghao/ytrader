# 宏观经济 CSV 种子数据

akshare 无法获取的指标，用 CSV 种子补齐历史时序。每月 job 运行时，
全量重新导入 CSV（幂等：按 (code, report_date) 主键 upsert，重复导入只覆写相同值）。

## 文件清单

| 文件 | code(s) | 来源 |
|---|---|---|
| cn_unemp.csv | cn_unemp_1624, cn_unemp_2529 | 国家统计局月度数据 |
| cn_disp_income.csv | cn_disp_income_median_yoy | 国家统计局季度公报 |
| cn_birth.csv | cn_birth | 国家统计年鉴 |
| cn_industrial_profit.csv | cn_industrial_profit_yoy | 国家统计局月度数据 |
| cn_trade_us.csv | cn_trade_us_amt | 海关总署月度数据 |
| cn_cpi_classified.csv | cn_cpi_food, cn_cpi_consumer | 国家统计局月度数据 |
| cn_sf_govbond.csv | cn_sf_govbond | 央行社融规模增量统计表 |
| cn_loan_split.csv | cn_loan_household, cn_loan_enterprise | 央行金融机构信贷收支表 |
| cn_fai.csv | cn_fai_yoy, cn_realestate_inv_yoy | 国家统计局月度数据 |

## CSV 格式

单指标：`report_date,value`（report_date 为 ISO 月初，如 2024-01-01）
双指标：`report_date,value1,value2`（value1/value2 对应 code 列表顺序）

## 数据更新

当前为占位示例数据。真实历史数据需从上述来源逐月整理补充。
更新 CSV 后，下次 job 运行时自动全量重新导入（幂等 upsert）。
