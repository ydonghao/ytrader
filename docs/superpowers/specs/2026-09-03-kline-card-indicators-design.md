# 看板 K 线卡片技术指标(MACD/RSI/BOLL)设计

日期:2026-09-03
状态:已落地(2026-09-03,实施计划 docs/superpowers/plans/2026-09-03-kline-card-indicators.md)
来源:用户需求——"K线走势的卡片,是否可以增加 macd、rsi、布林带这些技术指标"。

## 目标

- K 线卡支持三个技术指标,**用户已确认呈现方式**:
  - **BOLL 叠加主图**(蜡烛图上三条线,同价格轴);
  - **MACD、RSI 各自独立副图**(lightweight-charts 多窗格,与主图共享时间轴)。
- **用户已确认开关位置**:卡片 ⋯ 菜单内勾选,即时生效,随看板布局自动保存
  (复用现有 800ms 防抖 PUT 链路),不同卡片独立配置。
- **用户已确认参数可调**:MACD(fast/slow/signal)、RSI(period)、
  BOLL(period/stdDev),⋯ 菜单"指标参数…"弹窗内修改。
- 指标**纯前端计算**(数据卡片本来就整段拉回,零 API 改动),算法与后端
  `strategy/indicators.py` 逐条对齐,可数值互验。

## 非目标(YAGNI)

- 不做 KDJ/OBV/ATR 等更多指标(结构留好,后续加只是纯函数+序列)。
- 不做添加卡片弹窗里的指标初选(菜单勾选已覆盖,建卡默认全关)。
- 不做十字光标联动取值/指标数值悬浮提示(legend 静态展示指标名)。
- 不做参数记忆/全局默认(每卡独立,存进卡片 config)。
- 不做副图独立缩放/隐藏拖拽(v5 pane 自带交互,不额外定制)。

## 数据事实(已核实 2026-09-03)

- 前端 lightweight-charts **5.2.0**,`addSeries(definition, options, paneIndex)`
  多窗格已支持(typings.d.ts:1640);`chart.panes()` 可拿 IPaneApi 列表
  (typings.d.ts:1738),`setStretchFactor` 控制窗格高度比。
- 后端指标参考实现 `backend/src/domain/market/strategy/indicators.py`:
  - `ema`:前 period-1 位 None,**SMA 种子**,multiplier=2/(period+1);
  - `macd`:dif=fast_ema-slow_ema;**signal = EMA(dif 序列 None→0 填充, signal)**
    (注意:填充 0 参与前 signal 位 SMA 种子计算,前端必须复刻此行为);
  - `rsi`:Wilder 平滑,首值在 index=period,avg_loss=0 时直接 100;
  - `bollinger_bands`:mid=SMA,**σ 用样本标准差(statistics.stdev,n-1 分母)**,
    非 TA-Lib 的总体标准差——前端对齐 n-1 以保证互验一致。
- **坑:boardTypes.ts `normalizeLayout` 对 kline 卡当前强制 `config: {}`**
  (boardTypes.ts:250),指标配置存进去会在下次加载被清空,必须改为
  规范化保留(kline 分支专用 normalize)。
- KlineCard 现状(cards/KlineCard.tsx,202 行):pane 0 单窗格,蜡烛+成交量
  叠底(scaleMargins 0.8)+MA5/10/20/60 线,`limit=3000`,reqId 守卫防陈值;
  config 类型 `Record<string, unknown>`,当前恒为 `{}`。
- BoardCardShell ⋯ 菜单现有项:透明度/复制/置顶/置底/刷新/删除
  (BoardCardShell.tsx:164 附近),无扩展插槽。
- 前端无测试基建(无 jest/vitest,tsconfig 缺 jest/vite 类型库、无 eslint
  配置均为既有状态);验证路径=rsbuild 编译 + headless Chrome CDP 回归
  (先例:2026-09-03 uuid 修复回归)。
- MarketPage/indicators.ts 已有 RSI 是窗口重算版(非 Wilder),**不复用**,
  在 Board 下新建对齐后端的纯函数模块。

## 方案取舍

| 决策点 | 选择 | 理由 |
|---|---|---|
| 指标在哪算 | 前端纯函数(本设计) | bars 已整段在卡内,零 API/后端改动;后端库属策略回测域,拉端点反而加链路 |
| 指标模块放哪 | `Board/indicators.ts` 新建 | 对齐后端算法(Wilder/n-1/None→0),不污染 MarketPage 旧实现;纯函数好互验 |
| 参数 UI | ⋯菜单勾选 + "指标参数…"弹窗 | 勾选高频放菜单一级,改参数低频进弹窗;菜单内联数字输入太挤 |
| 菜单扩展机制 | BoardCardShell 加 `menuExtras` 插槽 | 卡片壳保持通用,kline 专属 UI 由 index.tsx 注入,不引入类型分支耦合 |
| 序列生命周期 | chart 实例常驻,序列随 config 增删 | 重建 chart 闪烁且丢缩放;v5 空窗格自动回收,增删序列即可 |

## 配置数据模型

`KlineCardData.config` 从 `Record<string, unknown>` 收紧为:

```ts
interface KlineIndicatorConfig {
  indicators: { macd: boolean; rsi: boolean; boll: boolean };  // 默认全 false
  params: {
    macd: { fast: number; slow: number; signal: number };  // 12 / 26 / 9
    rsi: { period: number };                                // 14
    boll: { period: number; stdDev: number };               // 20 / 2
  };
}
```

- `DEFAULT_KLINE_CONFIG` 常量导出(全关+默认参数);`normalizeKlineConfig(raw)`
  纯函数兜底:period/fast/slow/signal 钳制 ≥2 ≤250 整数,fast<slow 不满足时
  回默认;stdDev 钳制 0.5–5;布尔/缺字段回默认。
- `normalizeLayout` kline 分支改为 `config: normalizeKlineConfig(o.config)`;
  旧卡片 config 缺失 → 全部默认(指标关),完全向后兼容。
- 菜单写入走现有 `updateCard(id, {config: 新完整对象})`(read-modify-write,
  patch 是浅合并,必须整对象写入)。

## 指标纯函数模块(Board/indicators.ts)

签名与语义(全部:输入升序 closes,输出等长数组,不足周期位为 null):

```ts
ema(values: number[], period: number): (number | null)[]
macd(values, fast, slow, signal): { dif; dea; hist }  // 三条等长序列
rsiWilder(values, period): (number | null)[]
boll(values, period, stdDev): { upper; mid; lower }
```

实现逐条复刻后端(见"数据事实"四条要点,尤其 MACD 的 None→0 填充与
BOLL 的 n-1 分母)。模块无 React 依赖,后续任何图表可复用。

## 渲染设计(KlineCard)

- **窗格布局**:pane 0 = 蜡烛+成交量叠底+MA+BOLL 三线(价格轴);
  macd 开 → pane 1 = DIF 线+DEA 线+柱状图(hist,红涨绿跌着色,用
  chartTheme colorUp/colorDown)+零轴 priceLine;rsi 开 → 下一窗格 =
  RSI 线+30/70 两条 priceLine。
- **窗格高度**:`chart.panes()` 设 stretch factor,主图 3、各副图 1。
- **序列生命周期**:建图 effect 不变(常驻);新增 effect 监听 config,
  diff 出需增删的序列(addSeries 带 paneIndex / series.remove()),
  v5 空窗格自动消失。
- **预热窗口(计算正确性关键)**:EMA 类指标左侧需历史收敛。fetch 时若
  range.start 存在,请求 start 前扩 `WARMUP_CALENDAR_DAYS = 200` 自然日
  (覆盖默认参数及 slow≤60 的收敛);**展示仍切片回 [range.start, end]**,
  蜡烛/成交量/MA/指标全部只 setData 展示窗——主图可视范围与现状不变,
  同时顺带修了现状 MA60 左边缘缺值问题。start=null(全部)不前扩。
- **重算与重拉分离**:`barsRef` 缓存最近一次拉取的完整(含预热)bars;
  load()=拉取+存 ref;applySeries()=barsRef+config 纯渲染。参数/开关变化
  只触发 applySeries(不重新请求);symbol/区间/refreshKey 变化触发 load。
- **legend**:现有 MA 四色 chips 后按开启项追加 BOLL/MACD(DIF/DEA)/RSI
  静态名称 chips;配色:MACD dif `#f59e0b`、dea `#0a84ff`、BOLL `#22d3ee`、
  RSI `#ec4899`(延续 MA_COLORS 同风格,涨跌色用 chartTheme 常量)。

## 交互设计

- `BoardCardShell` 新增可选 prop
  `menuExtras?: (close: () => void) => React.ReactNode`,渲染在"复制卡片"
  之后、分隔线隔开;不传则菜单与现状完全一致。
- 新组件 `KlineIndicatorMenu.tsx`(Board/ 下):
  - 三个勾选行(MACD/RSI/布林带,checked 态打勾样式),点击即
    `updateCard` 翻转并 `close()` 菜单;
  - "指标参数…"行打开 Modal(复用 ui/Modal):三组数字输入(带标签与
    当前值,非法输入红字提示,确定才写入),写后同样走自动保存。
- `Board/index.tsx` renderCard 的 kline 分支注入 menuExtras=
  KlineIndicatorMenu(card, updateCard)。其余卡型不传。

## 文件清单

| 文件 | 动作 | 要点 |
|---|---|---|
| `pages/Board/indicators.ts` | 新增 ~120 行 | 纯函数四件套,对齐后端算法 |
| `pages/Board/boardTypes.ts` | 改 | config 类型化+normalizeKlineConfig+kline 分支不再清空 config |
| `pages/Board/cards/KlineCard.tsx` | 改 ~+130 行 | 窗格/序列生命周期+预热+重算+legend |
| `pages/Board/BoardCardShell.tsx` | 改 ~+6 行 | menuExtras 插槽 |
| `pages/Board/KlineIndicatorMenu.tsx` | 新增 ~150 行 | 勾选行+参数弹窗 |
| `pages/Board/index.tsx` | 改 ~+5 行 | kline 卡注入 menuExtras |
| `pages/Board/Board.css` | 改 ~+40 行 | 勾选行/参数弹窗/legend chips |

后端:无改动。

## 验证方案

1. **数值互验(一次性脚本,不入库)**:随机游走序列(含平台期/单边段,
   ≥500 点)分别用 node 跑前端模块、python 调后端 indicators.py,逐位
   比对 |Δ|<1e-9;MACD/RSI/BOLL 全覆盖。
2. **CDP 浏览器回归**(localhost:12000 即可,安全上下文不影响本特性):
   - 添加 K 线卡(搜索选标的)→ 菜单勾选 MACD/RSI/BOLL → 副图出现、
     BOLL 叠加主图、窗格高度比正确;
   - 参数弹窗改 RSI period=7 → 曲线变化且无重拉请求(Network 计数);
   - 刷新页面 → 配置持久化(自动保存链路 round-trip);
   - 旧看板(21年牛市熊市分析)加载无异常,kline 旧卡指标默认关;
   - 控制台零异常。
3. rsbuild 编译产物含新模块(热更新无报错)。

## 兼容性

- 旧 kline 卡 config 缺失/为空 → 默认全关,渲染与现状一致。
- normalizeLayout 收紧后不会再丢未知 kline config 字段(旧版丢的是 `{}`,
  无存量损失)。
