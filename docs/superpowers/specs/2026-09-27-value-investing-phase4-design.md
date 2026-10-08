# 价值投资四期设计 spec（打磨层·收官）

日期：2026-09-27
定位：功能饱和后的最后三件打磨。此后进入运行期，不再加功能。

## P1 历史买点地图

- 纯函数 `buy_point_map.py`：`buy_point_map(val_rows, price_rows,
  metric, band=0.10, horizons=[252, 756, 1260])`——历史某日指标值
  落在当前值 ±band 内 → 用价格序列算 N 交易日远期收益；输出
  每档 {n, avg, median, win_rate, p10, p90}。注记：历史研究非回测
  信号，含幸存者偏差。
- `GET /financial/buy-point-map/{symbol}?metric=pe_ttm&band=0.1`。
- ValuationHub 新卡（持有期分布表）。

## P2 分红税持有期提醒

- 纯函数：`dividend_tax(buy_date, ex_date)` → 个人差别化税率
  （<1月 20% / 1月-1年 10% / ≥1年 0%）+ 满一年免税日。
- `/thesis/dividend-calendar` 每条排期加 {tax_rate_pct, free_after}
  （按论点 buy_date 与预计除息月算）。
- 股息日历表加"税率"列。

## P3 周报自动生成

- 纯函数 `build_weekly_report(inputs)`：温度(今 vs 上周)/本周重估
  结论分布/新论点事件/管道滞留数/健康摘要/关闭后表现变化 →
  结构化 dict + markdown 文本。
- job `weekly_report`：周日 20:00 生成并存为 research_note
  （symbol='__weekly__'，零新表；/notes 页可见）。
- `POST /thesis/weekly-report/generate` 手动触发。
