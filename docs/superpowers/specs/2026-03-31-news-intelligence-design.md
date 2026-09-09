# 舆情情报模块 (News Intelligence)

**项目**: YTrader 量化交易平台
**模块**: News Intelligence (舆情情报)
**版本**: 1.0
**日期**: 2026-03-31
**状态**: 草稿

---

## 一、模块概述

舆情情报模块负责从多个中文平台聚合热点新闻和社交媒体内容，通过关键词过滤和加权评分算法筛选与用户持仓/关注标的相关的舆情信息，为投资决策提供情绪和事件支撑。

该模块是 AI Lab 的数据输入源之一，同时可独立为用户提供热点监控和推送服务。

---

## 二、数据源

### 2.1 聚合平台

基于 [newsnow](https://github.com/ourongxing/newsnow) API 聚合以下平台：

| 平台 ID | 平台名称 | 类型 |
|---------|---------|------|
| `toutiao` | 今日头条 | 新闻 |
| `baidu` | 百度热搜 | 热搜榜 |
| `wallstreetcn-hot` | 华尔街见闻 | 财经热点 |
| `thepaper` | 澎湃新闻 | 新闻 |
| `bilibili-hot-search` | B站热搜 | 热搜榜 |
| `cls-hot` | 财联社热门 | 财经热点 |
| `ifeng` | 凤凰网 | 新闻 |
| `tieba` | 贴吧 | 社区 |
| `weibo` | 微博热搜 | 热搜 |
| `douyin` | 抖音热搜 | 热搜 |
| `zhihu` | 知乎热榜 | 社区 |

### 2.2 扩展机制

新增平台只需在 `config/news_platforms.yaml` 中添加平台 ID 和名称，无需修改代码。

---

## 三、数据模型

### 3.1 NewsItem

```python
@dataclass
class NewsItem:
    id: str                          # 唯一标识 (platform_id + hash)
    title: str                       # 标题
    platform: str                    # 来源平台
    platform_id: str                 # 平台内 ID
    rank: int                        # 当平台内排名
    hotness: float                   # 热度值 (平台提供)
    url: str                         # 原文链接
    timestamp: datetime              # 采集时间
    keywords_matched: list[str]      # 匹配的关键词组
    sentiment: float | None          # 情感分数 (-1 到 1)
    entities: list[str]              # 识别的实体 (股票代码/公司名)
    metadata: dict                   # 平台原始附加数据
```

### 3.2 TopicCluster

```python
@dataclass
class TopicCluster:
    id: str
    title: str                       # 聚合主题
    news_items: list[NewsItem]       # 相关新闻
    first_seen: datetime
    last_updated: datetime
    trend_direction: str             # "rising", "falling", "stable"
    total_mentions: int              # 累计出现次数
    platform_breakdown: dict[str, int]  # 各平台分布
```

---

## 四、关键词过滤

### 4.1 过滤语法

支持三种关键词类型，通过配置文件的空行分隔形成独立的关键词组：

| 类型 | 语法 | 说明 |
|------|------|------|
| 普通词 | `AI` | 标题包含即匹配 |
| 必要词 | `+发布` | 同一行所有必要词必须同时出现 |
| 排除词 | `!广告` | 标题包含排除词则过滤 |

### 4.2 配置示例

```yaml
# 关键词配置 (config/keywords.yaml)
keyword_groups:
  - name: "科技"
    words: |
      AI
      人工智能
      芯片
      +发布
      !广告
    priority: 1

  - name: "金融"
    words: |
      A股
      上证
      +涨跌
      !预测
    priority: 2
```

### 4.3 匹配流程

```
标题输入
    ↓
按空行分组，逐组匹配
    ↓
组内规则：
  - 至少一个普通词匹配
  - 所有必要词都匹配
  - 没有排除词
    ↓
任意组匹配 → 通过过滤
```

---

## 五、加权趋势评分算法

### 5.1 三因子评分

每个新闻的最终分数由三个因子加权组成：

| 因子 | 权重 | 说明 |
|------|------|------|
| 排名分 (Rank) | 60% | 排名越靠前分数越高 |
| 频率分 (Frequency) | 30% | 跨平台出现次数 |
| 热度分 (Hotness) | 10% | 平台提供的热度值 |

### 5.2 计算公式

```python
def calculate_news_weight(news_items: list[NewsItem]) -> float:
    # 排名分：(11 - min(rank, 10)) / count
    rank_scores = []
    for item in news_items:
        rank_score = (11 - min(item.rank, 10)) / len(news_items)
        rank_scores.append(rank_score)

    # 频率分：min(count, 10) * 10
    frequency_score = min(len(news_items), 10) * 10

    # 热度分：(high_rank_count / total_count) * 100
    high_rank_count = sum(1 for item in news_items if item.rank <= 5)
    hotness_score = (high_rank_count / len(news_items)) * 100 if news_items else 0

    # 总分
    total = (sum(rank_scores) / len(rank_scores)) * 0.6 * 100 + \
            frequency_score * 0.3 + \
            hotness_score * 0.1

    return total / 100  # 归一化到 0-1
```

---

## 六、推送模式

### 6.1 三种模式

| 模式 | 说明 | 触发 |
|------|------|------|
| `daily` | 当日所有匹配新闻汇总 | 每日收盘后 |
| `current` | 当前排名匹配（显示排名变化） | 定时轮询 |
| `incremental` | 仅新出现的新闻（零重复） | 实时监控 |

### 6.2 推送时间窗口

```yaml
push_schedule:
  mode: "incremental"
  time_window:
    start: "08:30"
    end: "22:00"
  batch_interval: 300    # 5分钟聚合一次
  dedup_window: 1800    # 30分钟内去重
```

---

## 七、情感分析

集成 LLM API 进行零样本情感分类：

```python
async def analyze_sentiment(news_item: NewsItem, llm_client) -> float:
    prompt = f"""分析以下财经新闻的情感倾向，返回 -1 到 1 之间的分数：
    -1 = 极度负面/利空
     0 = 中性
    +1 = 极度正面/利多

    新闻标题：{news_item.title}
    """
    response = await llm_client.complete(prompt)
    return parse_sentiment_score(response)
```

---

## 八、多通道推送

### 8.1 支持的通道

| 通道 | 配置字段 | 限制 |
|------|---------|------|
| 企业微信 | `wechat.webhook_url` | 4000 字节/条 |
| 飞书 | `feishu.webhook_url` | 29KB/条 |
| 钉钉 | `dingtalk.webhook_url` | 20KB/条 |
| Telegram | `telegram.bot_token`, `telegram.chat_id` | 4000 字节/条 |
| 邮件 | `email.smtp_*` | 无限制 |

---

## 九、API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/news/latest` | GET | 最新聚合新闻 |
| `/news/trending` | GET | 趋势主题列表 |
| `/news/search` | GET | 关键词搜索新闻 |
| `/news/sentiment/{topic_id}` | GET | 主题情感分析 |
| `/news/clusters` | GET | 新闻聚类列表 |
| `WebSocket /news/ws` | WS | 实时增量推送 |

---

## 十、核心组件

| 组件 | 职责 |
|------|------|
| `NewsFetcher` | 调用 newsnow API 拉取各平台数据 |
| `KeywordFilter` | 关键词匹配和过滤 |
| `TrendingScorer` | 加权趋势评分计算 |
| `TopicClusterer` | 新闻聚类（标题相似度） |
| `SentimentAnalyzer` | LLM 驱动情感分析 |
| `PushDispatcher` | 多通道推送分发 |
| `PushRecordManager` | 推送去重和时间窗控制 |

---

**文档版本**: 1.0
**最后更新**: 2026-03-31
