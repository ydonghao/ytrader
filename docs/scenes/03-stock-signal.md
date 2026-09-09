# 场景三：股票情绪信号

## 目标

利用 NewsNow 热榜的情绪变化作为股票交易的辅助信号。

## 核心结论

**股票信号用专业博客文章（RSS），NewsNow 做辅助情绪指标。**

| 维度 | 专业博客 (RSS/Miniflux) | NewsNow 热榜 |
|------|------------------------|-------------|
| 内容深度 | ✅ 完整分析+数据 | ❌ 只有标题 |
| 因果推理 | ✅ 解释为什么 | ❌ 只知道什么 |
| Agent 支持 | ✅ 已有 4-stage pipeline | 需要新建 |
| 情绪速度 | ⚠️ 有延迟 | ✅ 实时 |
| 反转信号 | ⚠️ 事后分析 | ✅ 恐慌/贪婪指标 |

## 信号体系

### 已有：专业博客 Deep Analysis (4-stage pipeline)

```
Tagging → Celebrity(多角色辩论) → Trend → Report
```

输入: 有完整正文的 RSS 文章
输出: tags / industry / sentiment / 名人视角 / 趋势分析 / 投资建议

### 新增：SentimentPulse Agent

**输入**: `intel_rank_snapshot` 排名变化数据
**输出**: SentimentSignal

#### 检测模式

1. **恐慌抛售信号**: 微博/知乎突然大量某股票负面话题 + 排名飙升 → 可能是情绪底（反向指标）
2. **FOMO 信号**: 某概念股多平台霸榜 + 正面情绪 → 可能短期顶部
3. **量价背离信号**: 热榜讨论度飙升但股价没跟上 → 可能提前布局机会

### 新增：ReversalSignal Agent

基于历史回测验证：某种热榜模式出现后，股价 N 日内表现如何。

#### 数据源

- `intel_rank_snapshot` → 排名变化速度
- 跨平台共振度 → 同话题在 N 个平台出现
- 股价数据 → 对应时段涨跌幅
- 历史回测 → 统计显著性验证

### 融合层：SignalFusion

将 Deep Analysis 的基本面信号 + SentimentPulse 的情绪信号融合，
输出最终的交易建议。

## 状态

- [x] Deep Analysis 4-stage pipeline (已有)
- [ ] SentimentPulse Agent
- [ ] ReversalSignal Agent (需回测数据)
- [ ] SignalFusion 融合层
