# 资讯板块数据源规划

> 生成日期: 2026-05-31
> 视角: 2035 年回望，覆盖未来 10 年关键趋势

## 三个 Tab 架构

| Tab | 用途 | 主要数据源 |
|-----|------|-----------|
| 未来前沿 | 写公众号 + 前沿趋势追踪 | RSSHub (论文/媒体) + 官方 RSS |
| 财经情报 | 炒股决策 + 市场监控 | NewsNow + RSSHub + FinnHub |
| 社会热点 | 拓宽视野 + 内容素材 | TrendRadar MCP + NewsNow + RSSHub |

**共用层**: Miniflux (全量归档 + 全文搜索) / AI 处理 (摘要/情感/标签/重要性) / 飞书推送

---

## Tab 1: 未来前沿

### 1.1 AI / 机器学习

**arXiv 论文 (RSSHub):**
- `/papers/category/arxiv/cs.AI` — AI 论文
- `/papers/category/arxiv/cs.LG` — 机器学习论文
- `/papers/category/arxiv/cs.CL` — 自然语言处理论文
- `/papers/category/arxiv/cs.CV` — 计算机视觉论文
- `/papers/query/generative%20AI` — 生成式 AI
- `/papers/query/transformer` — Transformer 模型
- `/papers/query/reinforcement%20learning` — 强化学习

**公司博客:**
- `https://openai.com/news/rss.xml` — OpenAI 官方博客
- `https://deepmind.google/blog/rss.xml` — Google DeepMind
- `https://blog.google/technology/ai/rss/` — Google AI
- RSSHub: `/anthropic/news`, `/anthropic/research` — Anthropic
- RSSHub: `/huggingface/blog`, `/huggingface/blog-zh` — HuggingFace

**中文媒体:**
- RSSHub: `/aibase/daily` — AIbase AI 日报
- RSSHub: `/aibase/news` — AIbase AI 新闻
- `https://www.jiqizhixin.com/rss` — 机器之心
- RSSHub: `/juejin/trending/ai/weekly` — 掘金 AI 周榜

### 1.2 AGI 进展追踪 (新增)

- RSSHub: `/36kr/information/technology` — 36氪科技
- HN: `hnrss.org/newest?q=AGI`, `?q=artificial+general+intelligence`
- AIbase 融资动态
- 关键人物/公司动态追踪

### 1.3 AI 芯片 / 算力 (新增)

- arXiv: `/papers/category/arxiv/cs.AR` — 计算机架构
- HN: `hnrss.org/newest?q=NVIDIA`, `?q=AMD`, `?q=semiconductor`, `?q=chip`
- RSSHub: `/36kr/information/technology` (芯片相关)
- SemiAnalysis 等行业分析

### 1.4 AI 安全 / 监管 (新增)

- arXiv: `/papers/category/arxiv/cs.CY` — 计算安全
- HN: `hnrss.org/newest?q=AI+regulation`, `?q=AI+safety`
- RSSHub: `/solidot` — Solidot (奇客)
- RSSHub: `/36kr/newsflashes` — 36氪快讯 (政策类)

### 1.5 中美科技博弈 (新增)

- RSSHub: `/guancha/headline` — 观察者网
- RSSHub: `/solidot` — Solidot
- HN: `hnrss.org/newest?q=china+sanctions`, `?q=export+control`
- papers: US-China tech decoupling

### 1.6 机器人 / 具身智能

- arXiv: `/papers/category/arxiv/cs.RO` — 机器人论文
- arXiv: `/papers/query/humanoid%20robot` — 人形机器人
- arXiv: `/papers/query/embodied%20intelligence` — 具身智能
- `https://robohub.org/feed/` — Robohub 机器人社区
- HN: `hnrss.org/newest?q=robotics`, `?q=boston+dynamics`

### 1.7 新能源

- arXiv: `/papers/query/electric%20vehicle` — 电动汽车
- arXiv: `/papers/query/solar%20energy` — 太阳能
- arXiv: `/papers/query/battery` — 电池技术
- arXiv: `/papers/query/hydrogen%20fuel%20cell` — 氢燃料电池
- `https://www.nature.com/nenergy.rss` — Nature Energy
- HN: `hnrss.org/newest?q=electric+vehicle`, `?q=solar+energy`, `?q=battery+technology`

### 1.8 核聚变 (新增)

- arXiv: `/papers/query/nuclear%20fusion` — 核聚变论文
- HN: `hnrss.org/newest?q=fusion`, `?q=commonwealth+fusion`
- ITER 进展追踪

### 1.9 生物技术

- arXiv: `/papers/query/CRISPR%20gene%20editing` — CRISPR
- arXiv: `/papers/query/synthetic%20biology` — 合成生物学
- `https://www.nature.com/nbt.rss` — Nature Biotechnology
- `https://www.nature.com/nature.rss` — Nature 综合
- `https://rss.arxiv.org/rss/q-bio` — arXiv 定量生物学
- HN: `hnrss.org/newest?q=CRISPR`

### 1.10 脑机接口

- arXiv: `/papers/query/brain%20machine%20interface` — 脑机接口
- arXiv: `/papers/query/neural%20implant` — 神经植入
- arXiv: `/papers/category/arxiv/cs.HC` — 人机交互
- HN: `hnrss.org/newest?q=neuralink`, `?q=brain+computer+interface`

### 1.11 量子计算

- arXiv: `/papers/category/arxiv/quant-ph` — 量子物理
- arXiv: `/papers/query/quantum%20computing` — 量子计算
- `https://rss.arxiv.org/rss/quant-ph` — arXiv 量子物理 (直连)
- HN: `hnrss.org/newest?q=quantum+computing`

### 1.12 航天 / 太空

- arXiv: `/papers/query/space%20technology` — 航天技术
- arXiv: `/papers/query/space%20exploration` — 太空探索
- HN: `hnrss.org/newest?q=spacex`, `?q=space+exploration`

### 1.13 自动驾驶

- arXiv: `/papers/query/autonomous%20driving` — 自动驾驶
- HN: `hnrss.org/newest?q=autonomous+driving`, `?q=waymo`

### 1.14 综合科技媒体 (跨领域)

**RSSHub:**
- `/36kr/newsflashes` — 36氪快讯
- `/36kr/hot-list/24` — 36氪 24h 热榜
- `/36kr/information/web_news` — 36氪网络新闻
- `/36kr/information/technology` — 36氪技术
- `/sspai/matrix` — 少数派
- `/solidot` — Solidot 奇客
- `/oschina/news` — 开源中国
- `/juejin/trending/all/weekly` — 掘金周榜
- `/hackernews/best` — HN Best
- `/hackernews/newest` — HN Newest

**官方 RSS:**
- `https://techcrunch.com/feed/` — TechCrunch
- `https://www.theverge.com/rss/index.xml` — The Verge
- `https://www.wired.com/feed/rss` — Wired
- `https://feeds.arstechnica.com/arstechnica/index` — Ars Technica
- `https://www.technologyreview.com/feed/` — MIT Technology Review
- `https://hnrss.org/frontpage` — HN 头条

---

## Tab 2: 财经情报

### 2.1 实时快讯 (NewsNow localhost:4444)

- `wallstreetcn-hot` — 华尔街见闻
- `cls-hot` — 财联社
- `36kr` — 36氪
- `ithome` — IT之家

### 2.2 深度财经 (RSSHub localhost:1200)

- `/jin10` — 金十数据
- `/yicai/brief` — 第一财经
- `/caixin/latest` — 财新网
- `/guancha/headline` — 观察者网
- `/wallstreetcn/news/global` — 华尔街见闻全球
- `/sse/disclosure` — 上交所公告
- `/szse/notice` — 深交所公告

### 2.3 市场数据

- FinnHub API — 国际市场行情
- 上交所/深交所公告 (RSSHub)

### 2.4 宏观指标 (新增)

- RSSHub: `/jin10` (金十已有宏观数据频道)
- HN: `hnrss.org/newest?q=CPI`, `?q=interest+rate`, `?q=Fed`
- RSSHub: `/36kr/information/finance` — 36氪财经

### 2.5 地缘政治风险 (新增)

- RSSHub: `/guancha/headline` — 观察者网
- TrendRadar: 澎湃新闻
- HN: `hnrss.org/newest?q=geopolitics`, `?q=trade+war`, `?q=tariff`

### 2.6 全球市场联动 (新增)

- FinnHub: 美股/港股/欧洲指数
- HN: `hnrss.org/newest?q=stock+market`, `?q=S%26P+500`
- RSSHub: `/wallstreetcn/news/global` — 华尔街见闻全球

### 2.7 数字货币 / CBDC (新增)

- HN: `hnrss.org/newest?q=cryptocurrency`, `?q=CBDC`, `?q=DeFi`
- papers: digital currency
- RSSHub: `/jin10` (金十数字货币频道)

---

## Tab 3: 社会热点

### 3.1 国内平台热搜 (TrendRadar MCP localhost:3333)

9 个平台: 微博 · 知乎 · 抖音 · 今日头条 · 百度 · B站 · 澎湃新闻 · 凤凰网 · 贴吧

### 3.2 国内平台热搜 (NewsNow localhost:4444)

微博 · 知乎 · 抖音 · 头条 · 百度 · B站

### 3.3 热点新闻 (RSSHub)

- `/36kr/hot-list/24` — 36氪 24h 热榜
- `/hackernews/best` — HN Best

### 3.4 国际社交趋势 (新增)

- HN: `hnrss.org/frontpage` — HN 头条
- HN: `hnrss.org/newest?q=AI` — HN: AI
- RSSHub: Reddit 热门子版 (待配置)
- RSSHub: `/zhihu/hot` — 知乎热门

### 3.5 气候 / 极端天气 (新增)

- papers: climate change · extreme weather
- HN: `hnrss.org/newest?q=climate`, `?q=extreme+weather`

### 3.6 人口 / 社会趋势 (新增)

- papers: aging population · birth rate
- HN: `hnrss.org/newest?q=demographic`, `?q=population`

---

## 数据源类型速查

| 来源 | 端口 | 协议 | 用途 |
|------|------|------|------|
| NewsNow | 4444 | JSON API `/api/s?id={source}` | 国内热榜/财经快讯 |
| RSSHub | 1200 | RSS/XML `/papers/...` 等 | 论文/博客/媒体 RSS |
| TrendRadar MCP | 3333 | JSON-RPC (MCP) | 平台热搜聚合 |
| Miniflux | 8380 | REST API (HTTP Basic) | RSS 归档/全文搜索 |
| FinnHub | 外部 | REST API | 国际市场行情 |
| HackerNews | 外部 | RSS `hnrss.org` | 国际科技社区 |
| 官方博客 | 外部 | RSS/XML | 公司官方博客 |

## 采集频率建议

| 数据类型 | 频率 | 理由 |
|---------|------|------|
| 平台热搜 (TrendRadar) | 每 10 分钟 | 热搜变化快 |
| 财经快讯 (NewsNow) | 每 15 分钟 | 交易时段需要及时 |
| RSS 论文/博客 | 每 6 小时 | 论文/博客更新频率低 |
| Miniflux 归档同步 | 每 30 分钟 | RSS 归档不需要太高频率 |
| AI 处理 | 每 5 分钟 | 处理积压数据 |
| 飞书推送 - 每日热点 | 每日 8:00 | 早间阅读 |
| 飞书推送 - 前沿论文 Top10 | 每日 8:00 | 早间阅读 |
| 飞书推送 - 关键事件告警 | 实时 | 重大事件立即推送 |
