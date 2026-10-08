# 买入前检查清单(Buy Checklist)设计

日期:2026-09-20
状态:已确认(用户已批准方案A与21项清单、独立页面、纯手动手动项、只展示不下结论)
来源:用户需求——课程21《股票投资前的检查清单Checklist》"拿出来做一个功能,在我们购买股票前进行分析"
(`docs/策略/xhzl2/股票投资从入门到精通/21. 股票投资前的检查清单Checklist_哔哩哔哩_bilibili_BV1ksUKBgEEX_字幕.html`)。

## 课程方法论(功能灵魂)

- 买前按清单逐项过一遍,把公司业务/行业/财务/估值搞清楚,"能不能赚钱不好说,但一定不会踩大坑"。
- 糊弄的数据还不如不填:手动项须研究清楚了再填。
- 清单不是一劳永逸:投资后要定期复检(加仓减仓前重新过表)。
- 沉没成本不参与重大决策:已套牢持仓用本清单重新审视("假如空仓,还会买吗")。

## 用户已确认的三个决策

1. **独立页面**(非 Financial 页 Tab):新建 `/checklist` 路由,菜单名"买入体检",归"分析"组。
2. **定性项纯手动填写**(不接 AI 预填、不接 LLM)。
3. **只展示不下结论**:无总体红绿灯、无买/不买判定,每项仅展示数据与四态状态点,由用户自行判断。

## 非目标(YAGNI)

- 不做总体结论/评分/红绿灯(用户明确选择"只展示不下结论")。
- 不做 AI 辅助填写(用户明确选择"纯手动")。
- 不做清单历史快照/版本对比(仅保存最新一份;未来可加)。
- 不做车企月度产销模块(数据源缺失,清单中"业绩曲线"以年报口径为准)。
- 不做筹码获利比例(无数据源;用股东户数集中度趋势作代理参考,UI 明示"代理指标")。
- 不做强制门控(不阻止用户买入任何股票,本功能是分析工具非交易闸门)。

## 清单全景(四区 21 项:自动 12 + 手动 9)

状态四态:`ok` ✓ / `watch` ⚠ / `risk` ✗ / `missing` 暂无数据;手动项另有 `pending` 待填(进度计数)。**自动+可编辑项**(仅 2.5 上下游议价):状态来自自动计算(计入自动进度),编辑文本为可选补充(不计入手动进度)。

### 一、企业基本情况(手动 6,其中 3 项带自动参考)

| # | 项 | 类型 | 数据源/交互 |
|---|---|---|---|
| 1.1 | 公司全称 | 手动文本 | 参考区自动展示 `/financial/profile/{symbol}` 的名称 |
| 1.2 | 简介与使命愿景 | 手动多行文本 | 无参考(课程:官网可查) |
| 1.3 | 核心产品 | 手动多行文本 | 无参考 |
| 1.4 | 定价权 | 手动单选:是/否/不知道 | 参考区展示 `/financial/moat/{symbol}` 的 pricing_power_score(0-100)+解读 |
| 1.5 | 市场情况(增量/存量、市占率趋势、出海) | 手动多行文本 | 无参考 |
| 1.6 | 股权架构(国企/民企/家族/合伙/资本控股) | 手动单选 + 备注文本 | 参考区展示 `/financial/ownership/{symbol}` 前十大股东(名称/占比/性质) |

### 二、行业分析(自动 2 + 手动 3)

| # | 项 | 类型 | 数据源 |
|---|---|---|---|
| 2.1 | 所属行业 | 自动 | 申万行业截面(`/financial/industry-members/{symbol}` 或 profile 的行业字段);status 恒 ok/missing |
| 2.2 | 行业周期 | 手动单选:导入期/成长期/成熟期/衰退期 | 课程四阶段对照表常驻 UI |
| 2.3 | 竞争格局 | 手动单选:百舸争流/一超多强/巨头垄断 | 参考区展示截面 CR4/HHI(来自 industry-peers 的 sections) |
| 2.4 | 微笑曲线位置 | 手动单选:左端研发设计/中间制造/右端品牌营销 + 备注 | 课程微笑曲线示意常驻 UI |
| 2.5 | 上下游议价能力 | **自动+可编辑** | 五力自动结论默认展示(`/financial/five-forces/{symbol}` 供应商/客户两轴评分+证据);用户可在其下文本框补充/修正自己的判断(存 `stock_checklist_item`, item_key=`bargaining_power_note`),自动值始终保留并列展示 |

### 三、财务指标(自动 5)

| # | 项 | 类型 | 数据源与阈值 |
|---|---|---|---|
| 3.1 | 业绩曲线(成长性) | 自动 | 营收/净利多期序列 + 近8年营收CAGR;CAGR<3% → watch(课程"格力停滞"口径) |
| 3.2 | 资产负债表健康 | 自动 | `/financial/liquidity/{symbol}`(strong/healthy/stretched/risky)+固定资产占比(重资产标注) |
| 3.3 | ROE | 自动 | 最新 ROE + 行业分位(截面 distribution.roe);<8% watch、连续下滑 watch |
| 3.3' | ROE 横向对比 | 自动(并入3.3) | 同行业 peers ROE 对比(来自 five_forces/industry_peers 既有取数) |
| 3.4 | 分红 | 自动 | `/financial/quality` 派息率分档:≤30% 正常 / 30-70% 慷慨 / >70% 掏空家底风险 risk |
| 3.5 | 财务红旗 | 自动 | `/financial/fraud-signals` + `/financial/z-score` + `/financial/m-score` 三者汇总;任一 high_risk/distress/manipulator → risk |

### 四、股价与估值(自动 5)

| # | 项 | 类型 | 数据源与阈值 |
|---|---|---|---|
| 4.1 | 市值规模 | 自动 | stock_valuation.total_mv 最新值 + 分档(≥千亿/百亿/十亿/十亿以下) |
| 4.2 | PE 估值带 | 自动 | `/financial/valuation-band/{symbol}`(8年窗 μ±1σ, z-score 四档) |
| 4.3 | PS 估值带 | 自动 | 同上(PS 维度);利润不稳/成长股提示"看 PS 更合适"(课程口径) |
| 4.4 | K线趋势 | 自动 | **新纯函数**:日频收盘 MA20/MA60/MA120 + 120日线性回归斜率 → 上升/下降/横盘;数据源 `/market/kline/{symbol}` |
| 4.5 | 筹码参考(代理) | 自动 | `/financial/concentration/{symbol}` 股东户数集中度趋势;UI 注明"获利比例无数据源,此为代理指标" |

## 架构(方案A:后端聚合端点,对齐五力模块范式)

三层:纯函数(零IO) → handler(串调既有函数,不重复取数) → router → 前端页面。

```
backend/src/domain/market/fundamental/checklist_status.py   # 新:状态映射纯函数
backend/src/domain/market/fundamental/kline_trend.py        # 新:K线趋势纯函数
backend/src/infra/database/market/checklist.py              # 新:StockChecklistItem 表+Repo
backend/src/api/handler/checklist_handler.py                # 新:聚合串调
backend/src/api/router/checklist_router.py                  # 新:3端点
frontend/apps/web/src/pages/Checklist.tsx + .css            # 新:独立页面
```

### 数据模型

```python
class StockChecklistItem(SQLModel, table=True):
    __tablename__ = "stock_checklist_item"
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True)          # 小写带前缀,如 sh600519
    item_key: str                            # 如 "pricing_power", "industry_cycle"
    value_text: Optional[str] = None         # 多行文本项
    value_choice: Optional[str] = None       # 单选项
    updated_at: datetime
    # UNIQUE(symbol, item_key); upsert 语义
```

### API(前缀 /checklist)

1. `GET /checklist/{symbol}` — 聚合返回:
   ```json
   {
     "symbol": "sh600519",
     "sections": [
       {"key": "company", "title": "一、企业基本情况", "items": [...]},
       ...四区...
     ],
     "manual_progress": {"filled": 3, "total": 9},
     "auto_progress": {"ok": 9, "watch": 2, "risk": 1, "missing": 0},
     "references": {...}   // 定价权评分/前十大股东/CR4/微笑曲线等参考数据
     // 注意:无 verdict/conclusion 字段(只展示不下结论)
   }
   ```
   每个自动项 item:`{key, title, status, value, detail, hint}`,hint 为课程口径解读文案。每个手动项 item:`{key, title, input_type: "text"|"choice"|"choice+text", choices?: [...], value_text?, value_choice?, updated_at?, status: "pending"|已填}`。
2. `PUT /checklist/{symbol}/items` — 批量保存手动项(body: `{items: [{item_key, value_text, value_choice}]}`);空文本/空选项=清空该项(回到 pending)。

共 2 个端点(K线趋势并入 GET 聚合,避免多请求)。

**"已填"判定**:单选/单选+文本项 `value_choice` 非空即已填(文本可空);纯文本项 `value_text` 非空(trim 后)即已填。

### handler 串调清单(全部既有内部函数,不新增取数)

`stock_profile` / `fetch_financial_history`(业绩序列)/ `liquidity()` / `ratios()` 或 quality(ROE+派息率)/ `fraud+z+m` / `valuation_band` / `concentration` / `five_forces` / 截面仓库 CR4/HHI / kline 查询 + 新 `kline_trend` 纯函数。任一子源异常:该项 status=missing,不阻塞整页(逐项 try/except)。

### 前端

- 路由 `/checklist`(App.tsx lazy),Layout "分析"组加 `{path: '/checklist', label: '买入体检'}`。
- 页面结构:顶部 StockSearch(从 Financial.tsx:181 抽出共享或复制轻量版——**决定:抽出共享**,`components/StockSearch.tsx`,Financial 改引)/ 股票名与最新价概况 → 四张分区卡片纵向排列。
- 分区卡片:标题 + "已填 x/y"(手动)或状态统计(自动);项行布局:状态点 | 项名 | 值/输入框 | 课程口径 hint(tooltip 或折叠)。
- 手动项:输入框/单选,失焦或 800ms 防抖自动保存(复用看板防抖链路模式),右上角"上次填写 3 天前"(复检提醒,>90天变 ⚠ 提示"建议复检")。
- 自动项:数据值 + 状态点;点击展开 detail(如业绩曲线迷你图、估值带位置说明、五力两轴证据列表)。
- 每项带"课程原文"折叠(该检查项在课程中的方法论一句话),保持功能与课程可溯源。

### 测试

- pytest:checklist_status 纯函数 ~20 用例(阈值边界:CAGR 3%/3.01%、派息率 70%/70.1%、z-score 边界、ROE 分位、kline_trend 升/降/横盘/数据不足);repo upsert 语义;handler 逐项 missing 降级(mock 子源异常)。
- 基线:388 纯函数测试保持全绿(既有命令,见项目记忆)。
- 前端:rsbuild 编译通过 + 浏览器手工冒烟(选股→自动项加载→手动项填写保存→刷新回显)。

## 错误处理

- 子数据源异常/缺数:单项 missing,页面正常渲染其余项(核心原则:一张表能填多少看多少,缺失不阻塞)。
- PUT 空值:视为清除该项(回到待填),不报错。
- symbol 不存在:GET 返回 404(对齐既有端点行为);profile 之外全部 missing 时也照常返回。

## 实施顺序(写实施计划时展开)

1. 表+Repo+main.py 注册 → 2. 两个纯函数模块+测试 → 3. handler 聚合+router+注册 → 4. StockSearch 抽取共享 → 5. Checklist 页面四区渲染 → 6. 防抖保存链路 → 7. 编译+冒烟+全量纯函数回归。
