# 宏观图表历史事件标注 + 长历史数据 — 设计文档

> 日期：2026-07-24
> 状态：待评审
> 关联：macro-monthly-sync（数据层）、macro-frontend-redesign（Tab+详情面板）

## 1. 背景与目标

宏观页面已完成 Tab 浏览 + 指标详情面板（折线图+表格+解释）。用户提出两个增强：

1. **历史事件标注**：详情面板的大折线图上标注中国重大经济事件（2008 金融危机等），让数据有上下文
2. **补长历史数据**：中国核心指标（CPI/PPI/PMI/M2）目前只有 ~18 年（2008 起），用户要 30 年

**关键发现**：akshare 的 `*_yearly` 接口实际是**更深历史的月度数据**（不是年度颗粒度），但日期语义不同（发布日 vs 数据所属月），不能直接混用。

## 2. 方案

### 2.1 历史事件标注

**事件数据**：在 `conf/config.yaml` 新增 `macro_events` 配置段，定义为静态数据（不来自 API）。约 12 个中国重大经济事件：

```yaml
macro_events:
  - date: "2008-09-15"
    title: "雷曼破产·全球金融危机"
    desc: "次贷危机全面爆发，中国出口骤降，11月推出四万亿刺激"
  - date: "2009-03-01"
    title: "四万亿投资计划"
    desc: "大规模基建刺激，M2 增速飙至 30%"
  - date: "2015-06-15"
    title: "A股股灾"
    desc: "杠杆牛破裂，上证从5178跌至2850"
  - date: "2016-01-01"
    title: "供给侧改革"
    desc: "去产能去库存，PPI 从通缩转正"
  - date: "2018-07-06"
    title: "中美贸易战"
    desc: "首批340亿美元商品加征关税"
  - date: "2020-01-23"
    title: "新冠疫情"
    desc: "武汉封城，一季度GDP -6.9%"
  - date: "2020-03-01"
    title: "全球大放水"
    desc: "美联储无限QE，全球资产反弹"
  - date: "2021-07-01"
    title: "互联网/教培监管"
    desc: "反垄断+双减，恒生科技暴跌"
  - date: "2022-07-01"
    title: "房地产断贷潮"
    desc: "保交楼，房企信用危机"
  - date: "2022-11-01"
    title: "防疫优化二十条"
    desc: "逐步放开，经济复苏预期"
  - date: "2024-09-24"
    title: "924 金融新政"
    desc: "降准降息+股市支持，A股暴涨"
  - date: "2025-04-01"
    title: "对等关税升级"
    desc: "中美贸易紧张再升温"
```

**后端**：在 `macro_handler.py` 新增 `GET /macro/events` 端点，返回事件列表。事件数据从 `config.yaml` 读取。

**前端**：在 `IndicatorDetail` 的大折线图上，用 recharts `ReferenceLine` 画竖线（`x={event.date}`），竖线旁标注事件标题。鼠标悬浮 tooltip 显示事件描述。所有指标共用同一套事件。

### 2.2 长历史数据

**数据源**：akshare `*_yearly` 接口（更深历史的月度数据）：

| 指标 | 现有（月度接口） | 新增（yearly 接口） | code |
|---|---|---|---|
| CPI 同比 | cn_cpi_yoy (2008+) | cn_cpi_yoy_long (**1986+**) | macro_china_cpi_yearly |
| PPI 同比 | cn_ppi_yoy (2006+) | cn_ppi_yoy_long (**1995+**) | macro_china_ppi_yearly |
| PMI | cn_pmi (2008+) | cn_pmi_long (**2005+**) | macro_china_pmi_yearly |
| M2 同比 | cn_m2_yoy (2008+) | cn_m2_yoy_long (**1998+**) | macro_china_m2_yearly |

**存储**：`_long` 后缀的独立 code，不与现有月度数据混。日期用年度接口的原始日期（发布日），不做归一化（前端切换时知道这是不同口径）。

**前端**：详情面板的图表上方加一个频率切换按钮（"标准" / "长历史"）。切换时调不同 code 的 API。只有这 4 个指标有 `_long` 版本时才显示切换按钮。

### 2.3 改动范围

| 文件 | 动作 | 说明 |
|---|---|---|
| `conf/config.yaml` | Modify | 新增 `macro_events` 段 + 4 个 `_long` 指标元数据 |
| `conf/settings.py` | Modify | 新增 `MacroEvent` 模型 + `macro_events` 字段 |
| `backend/.../akshare_provider.py` | Modify | `_MACRO_EXTRACTORS` 新增 4 个 `_long` 提取器 |
| `backend/.../macro_handler.py` | Modify | 新增 `list_events()` handler |
| `backend/.../macro_router.py` | Modify | 新增 `GET /macro/events` 路由 |
| `backend/.../macro_monthly.py` | Modify | `_long` code 加入 akshare 同步列表 |
| `frontend/.../Macro.tsx` | Modify | 事件标注 + 频率切换 |
| `frontend/.../Macro.css` | Modify | 事件标注 + 切换按钮样式 |

## 3. 数据流

### 事件标注
```
config.yaml macro_events → settings.py MacroEvent
→ GET /macro/events → 前端 IndicatorDetail → recharts ReferenceLine
```

### 长历史
```
akshare *_yearly → _MACRO_EXTRACTORS[xxx_long] → macro_monthly job upsert
→ GET /macro/indicators/cn_cpi_yoy_long → 前端切换 → IndicatorDetail 大图
```

## 4. 不做的事（YAGNI）

- ❌ 不做日期归一化（`_long` 用原始发布日，与标准版口径不同，前端标注）
- ❌ 不做事件编辑 UI（静态配置）
- ❌ 不给所有指标加 `_long`（只有 4 个有 yearly 接口的核心指标）
- ❌ 不做事件按指标过滤（所有指标共用全量事件）
