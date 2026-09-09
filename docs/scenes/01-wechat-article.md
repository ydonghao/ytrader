# 场景一：微信公众号自动写作

## 目标

从 NewsNow 12 平台热榜中发现高价值选题，自动生成微信公众号文章。

## 核心思路

**跨平台趋势聚合 → 选题评分 → 内容增强 → 文章生成**

NewsNow 的价值不在内容（只有标题），在选题。通过跨平台共振检测发现值得写的热点，
再从已有的 RSS/MRSS 库（有正文）中检索相关素材，最终生成独家视角的文章。

## Agent 流水线

```
NewsNow 12 平台热榜 (intel_rank_snapshot)
                │
        ┌───────▼───────┐
        │ TrendSpotter  │  跨平台热点聚合
        │               │  - 跨平台相似度匹配
        │               │  - 排名变化速度计算
        │               │  - 选题评分 (score)
        └───────┬───────┘
                │
        同一话题出现在 ≥3 个平台 = 强信号
                │
        ┌───────▼───────┐
        │ ContentEnrich │  内容增强
        │               │  - 从 intel_news 全文检索相关文章
        │               │  - 爬取原始 URL 获取全文
        └───────┬───────┘
                │
        ┌───────▼───────┐
        │ ArticleWriter │  微信文章生成
        │               │  - 标题 + 摘要 + 正文(1500-3000字)
        │               │  - 独家视角、数据驱动
        └───────────────┘
```

## TrendSpotter Agent

**输入**: `intel_rank_snapshot` 最近 N 小时的排名数据
**输出**: `TrendTopic[]` — 跨平台聚合后的热点话题列表

### 评分公式

```
score = cross_platform_count × rank_momentum × platform_weight
```

- `cross_platform_count`: 同一话题出现在几个平台 (0-12)
- `rank_momentum`: 排名上升速度 (当前排名 vs 上次快照)
- `platform_weight`: 平台权重 (微博=1.2, 知乎=1.1, 抖音=1.0, ...)

### 跨平台相似度

用 LLM 对同一时段内的所有热榜标题做语义聚类，将相似标题归为同一个"热点事件"。
例如：微博"AI 大模型新突破" + 知乎"GPT-5 发布" → 同一热点。

## ContentEnrich Agent

**输入**: TrendTopic (标题 + 跨平台来源)
**输出**: EnrichedContent — 相关素材合集

### 数据源

1. `intel_news` 全文检索 — 已有的 RSS 文章（有正文）
2. 原始 URL 爬取 — 如果话题关联的 URL 可访问
3. 交叉引用 — 相关历史文章的 agent 深度分析结果

## ArticleWriter Agent

**输入**: TrendTopic + EnrichedContent
**输出**: WechatArticle

### 输出格式

```json
{
  "title": "吸引人的标题",
  "summary": "200字摘要",
  "body_markdown": "1500-3000字正文 (Markdown)",
  "cover_suggestion": "封面图建议",
  "tags": ["标签1", "标签2"],
  "source_refs": ["引用来源1", "引用来源2"]
}
```

## 状态

- [ ] TrendSpotter Agent
- [ ] ContentEnrich Agent
- [ ] ArticleWriter Agent
- [ ] API 路由 + 前端 UI
