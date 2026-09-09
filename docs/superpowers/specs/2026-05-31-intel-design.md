# 资讯板块设计文档

> 日期: 2026-05-31
> 状态: 待实现

## 背景

ytrader 是一个量化交易平台，用户有三个核心需求：
1. **AI/前沿科技内容创作** — 追踪前沿动态用于写微信公众号
2. **炒股决策支持** — 财经新闻、市场情绪、热点关联个股
3. **社会热点关注** — 拓宽视野，部分热点与炒股和公众号创作相关

本地已部署 4 个 Docker 数据采集服务（NewsNow、RSSHub、TrendRadar、Miniflux），需要将其集成到 ytrader 的资讯板块中。

## 架构决策

**方案 A: ytrader 后端做数据中枢**

所有数据汇聚到后端，统一入库 + AI 处理 + 飞书推送。前端只对接 ytrader API，不直接访问 Docker 服务。

理由：需要 AI 处理（摘要/情感/标签）、飞书推送、跨板块搜索，这些都要求数据在后端汇聚。

## 三个 Tab

| Tab | Category | 用途 | 主要数据源 |
|-----|----------|------|-----------|
| 未来前沿 | `future_tech` | 写公众号 + 前沿追踪 | RSSHub (论文/媒体) + 官方 RSS + HN |
| 财经情报 | `finance` | 炒股决策 | NewsNow + RSSHub + FinnHub |
| 社会热点 | `hotlist` | 拓宽视野 + 内容素材 | TrendRadar MCP + NewsNow |

**共用层**: Miniflux (全量归档 + 全文搜索) / AI 处理 (摘要/情感/标签/重要性) / 飞书推送

### 未来前沿 — 数据源

覆盖 10+ 前沿领域，含 arXiv 实时论文监测：

- **AI/ML**: arXiv cs.AI/LG/CL/CV + OpenAI/Anthropic/DeepMind/Google AI/HuggingFace + AIbase + 机器之心
- **AGI 进展**: 公司动态、融资事件、关键人物
- **AI 芯片/算力**: arXiv cs.AR + HN: NVIDIA/AMD/semiconductor + 36氪
- **AI 安全/监管**: arXiv cs.CY + HN: AI regulation/safety
- **中美科技博弈**: 观察者网 + Solidot + HN: sanctions/export control
- **机器人/具身智能**: arXiv cs.RO + Robohub
- **新能源**: arXiv: EV/solar/battery/hydrogen + Nature Energy
- **核聚变**: arXiv: nuclear fusion + HN: fusion
- **生物技术**: arXiv: CRISPR/synthetic biology + Nature Biotech
- **脑机接口**: arXiv: brain machine interface + HN: neuralink
- **量子计算**: arXiv quant-ph + HN: quantum computing
- **航天/太空**: arXiv: space technology + HN: SpaceX
- **自动驾驶**: arXiv: autonomous driving + HN: waymo
- **综合科技**: 36氪/少数派/Solidot/HackerNews/TechCrunch/MIT Tech Review/Wired/The Verge/Ars Technica

### 财经情报 — 数据源

- **实时快讯**: NewsNow (华尔街见闻/财联社/36氪/IT之家)
- **深度财经**: RSSHub (金十/第一财经/财新/观察者/华尔街见闻全球/上交所/深交所)
- **市场数据**: FinnHub API
- **宏观指标**: 金十(宏观数据) + HN: CPI/interest rate/Fed + 36氪财经
- **地缘政治**: 观察者网 + 澎湃 + HN: geopolitics/trade war
- **全球市场**: FinnHub(美股/港股/欧洲) + HN: stock market
- **数字货币/CBDC**: HN: cryptocurrency/CBDC/DeFi + 金十

### 社会热点 — 数据源

- **国内热搜**: TrendRadar MCP (微博/知乎/抖音/头条/百度/B站/澎湃/凤凰/贴吧)
- **NewsNow 热榜**: 微博/知乎/抖音/头条/百度/B站
- **热点新闻**: 36氪 24h 热榜 + HN Best
- **国际趋势**: HN frontpage + Reddit
- **气候/极端天气**: arXiv: climate change + HN: climate
- **人口/社会**: arXiv: aging population + HN: demographic

完整数据源列表见: `docs/superpowers/specs/2026-05-31-intel-datasources.md`

## 后端设计

### Provider 清单

| Provider | 状态 | 数据源 | Category |
|----------|------|--------|----------|
| RSSProvider | 已有，改 URL | RSSHub + 官方 RSS | future_tech |
| NewsnowProvider | 已有，改 base_url | NewsNow (localhost:4444) | finance, hotlist |
| FinnHubProvider | 已有，无改动 | FinnHub API | finance |
| TrendRadarProvider | **新增** | TrendRadar MCP (localhost:3333) | hotlist |
| MinifluxProvider | **新增** | Miniflux REST API (localhost:8380) | 搜索共用 |

### Models 扩展

`NewsCategory` 从 5 个精简为 3 个:
- `FUTURE_TECH = "future_tech"`
- `FINANCE = "finance"`
- `HOTLIST = "hotlist"`

`NewsItem` 新增字段:
- `platform: str | None` — 来源平台 (微博/知乎等)
- `rank: int | None` — 热搜排名
- `heat_score: float | None` — 热度分数

### API Endpoints

```
GET  /intel/news?category=&page=&size=       # 通用列表 (3 Tab 共用)
GET  /intel/news/search?q=&category=         # 搜索 (含 Miniflux 归档)
GET  /intel/news/trending?hours=&category=   # 趋势排行
GET  /intel/hotlist?platform=                # 社会热点 (平台过滤)
GET  /intel/sources                          # 数据源健康
GET  /intel/stats                            # 统计
POST /intel/collect?category=                # 手动采集
POST /intel/process                          # 手动 AI 处理
GET  /intel/daily-brief                      # 每日摘要
```

### 调度任务

| 任务 | 频率 | 说明 |
|------|------|------|
| 社会热点采集 | 每 10 分钟 | TrendRadar + NewsNow 热搜 |
| 财经情报采集 | 每 15 分钟 | NewsNow + RSSHub 财经 |
| 未来前沿采集 | 每 6 小时 | 论文/博客更新频率低 |
| Miniflux 同步 | 每 30 分钟 | RSS 归档 |
| AI 处理 | 每 5 分钟 | 摘要/情感/标签/重要性 |
| 飞书每日热点 | 每日 8:00 | 三个 Tab 热点摘要 |
| 飞书前沿论文 Top10 | 每日 8:00 | 高影响力论文 |
| 关键事件告警 | 实时 | 采集后判断重要性 |

### 飞书推送

复用现有 `src/infra/notification/feishu.py` 模块，新增推送模板：
- **每日热点摘要**: 三个 Tab 各 Top 5，含标题 + AI 摘要 + 链接
- **前沿论文 Top10**: 按重要性排序，含论文标题 + 摘要 + arXiv 链接
- **关键事件告警**: 重要性 >= 0.9 的新闻立即推送

## 前端设计

### 页面结构

重建 `Intel.tsx` 和 `Intel.css`，删除旧版 `News.tsx` 和 `News.css`。

**布局:**
- 顶部: 3 个 Tab 切换 + 搜索框 + 手动采集按钮
- 左侧主区域: 子分类 chips + 新闻卡片列表
- 右侧边栏: 数据概览 + 热门话题 + 数据源健康状态

**子分类 chips (按 Tab 不同):**
- 未来前沿: 全部/AI·ML/机器人/新能源/量子计算/脑机接口/AI芯片/AGI/生物技术/航天/自动驾驶
- 财经情报: 全部/快讯/深度/宏观/地缘/全球/数字货币
- 社会热点: 全部/微博/知乎/抖音/头条/百度/B站/澎湃

**新闻卡片字段:**
- 标题 + 发布时间
- 子分类标签 + 来源标签
- 重要性星级 (1-5)
- 情感标签 (利好/利空/中性)
- AI 摘要 (展开显示)

**搜索:** 顶部搜索框，搜索时同时查 ytrader 数据库 + Miniflux 归档，合并去重返回。

### 路由

- `/intel` — 资讯中心 (替换旧版)
- 删除 `/news` 路由

## 文件变更清单

### 后端 — 修改

| 文件 | 改动 |
|------|------|
| `backend/conf/config.yaml` | 添加本地 Docker 端点 + 新 RSS 源 |
| `backend/conf/settings.py` | 添加 Miniflux/TrendRadar Pydantic 模型 |
| `backend/src/domain/market/intel/models.py` | Category 精简为 3 个 + 新增字段 |
| `backend/src/domain/market/intel/collector.py` | 接入新 Provider |
| `backend/src/domain/market/intel/providers/newsnow_provider.py` | base_url 改 localhost |
| `backend/src/domain/market/intel/providers/rss_provider.py` | 无大改，URL 由配置驱动 |
| `backend/src/api/router/intel_router.py` | 更新 endpoints |
| `backend/src/infra/scheduler.py` | 添加新调度任务 |
| `backend/src/api/router/__init__.py` | 添加 intel_router |

### 后端 — 新增

| 文件 | 说明 |
|------|------|
| `backend/src/domain/market/intel/providers/miniflux_provider.py` | Miniflux REST + 搜索 |
| `backend/src/domain/market/intel/providers/trendradar_provider.py` | TrendRadar MCP JSON-RPC |
| `backend/src/domain/market/intel/push_service.py` | 飞书推送服务 |

### 前端 — 新增/重建

| 文件 | 说明 |
|------|------|
| `frontend/apps/web/src/pages/Intel.tsx` | 重建，3 Tab + 搜索 + 侧边栏 |
| `frontend/apps/web/src/pages/Intel.css` | 重建，深色主题 |

### 前端 — 删除

| 文件 | 说明 |
|------|------|
| `frontend/apps/web/src/pages/News.tsx` | 删除旧版 |
| `frontend/apps/web/src/pages/News.css` | 删除旧版 |

## 验证计划

1. 启动 Docker 服务: `cd docker && docker compose up -d`
2. 启动后端: `cd backend && python main.py`
3. 测试 API:
   - `curl localhost:8000/api/v1/intel/news?category=future_tech` — 未来前沿列表
   - `curl localhost:8000/api/v1/intel/news?category=finance` — 财经情报列表
   - `curl localhost:8000/api/v1/intel/hotlist` — 社会热点
   - `curl localhost:8000/api/v1/intel/news/search?q=AI` — 搜索
   - `curl -X POST localhost:8000/api/v1/intel/collect` — 手动采集
4. 启动前端: `cd frontend && pnpm dev`
5. 打开 `/intel`，验证 3 个 Tab 切换、子分类过滤、搜索、热门话题
6. 检查调度器: `curl localhost:8000/api/v1/system/scheduler`
7. 验证飞书推送: 手动触发每日摘要，检查飞书机器人消息
