# 交互式 Blog Pipeline（两道人工关卡）— 设计

> 日期：2026-06-17
> 状态：已确认
> 决策：去定时任务；选题 + 素材 改为人工确认（两道关卡），再写作

## 改动
1. **去掉** scheduler `blog_daily_generation`（不再自动定时生成）
2. **拆 pipeline 为 3 阶段**，中间两道人工关卡（前端向导）

## 3 阶段流程
```
阶段1（选题关卡）：
  POST /blog/suggest-topics?topic=ai_tech → _discover_topics 返回候选选题
  前端：罗列候选（多选）或输入新选题 → 选定选题[]

阶段2（素材关卡）：
  POST /blog/suggest-articles（选定选题）→ article_retrieval 返回候选素材
  前端：每选题罗列候选文章（多选）→ 选定素材

阶段3（写作）：
  POST /blog/write（选定选题 + 选定素材）→ deep → writer → editor → N 篇（每选题1篇）
```

## 新增 API
- `POST /blog/suggest-topics?topic=` → 候选选题（_discover_topics）
- `POST /blog/suggest-articles`（body: topic_hint[]）→ 每选题候选素材
- `POST /blog/write`（body: [{topic_hint, article_ids}]）→ 写作 N 篇 + run_id

## 前端
BlogDraft 加"交互式生成"向导（3 步）：选题勾选 → 素材勾选 → 写作（liveTrace）。

## 复用
_discover_topics / article_retrieval / deep / writer / editor / trace / 异步 都现成，只拆阶段 + 加向导。

## 实施
1. 去 scheduler blog_daily_generation
2. suggest-topics API（_discover_topics）
3. suggest-articles API（article_retrieval）
4. write API（选定选题+素材 → pipeline）
5. 前端 3 步向导
