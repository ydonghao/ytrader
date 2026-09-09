# 自定义主题生成 — 设计文档

> 日期：2026-06-17
> 状态：已确认，待 review → 实施
> 决策：用户输入主题 → 全源搜素材（miniflux/wewe + newsnow）→ 复用 pipeline → 1 篇草稿

---

## 1. Context

现有 blog 是**自动选题**（3 专题各选 3 话题）。新增：**用户指定主题**，大模型搜素材 + 编写 1 篇。

与自动选题的区别：主题用户定（不限于 AI/炒股）、搜全源（深度 + 热点）、1 篇。

---

## 2. 设计

### 流程
```
用户输入主题（如"AI 如何改变教育"）
  → article_retrieval【全源搜】
      • miniflux/wewe（按主题关键词搜深度文章，strict 模式，有正文）
      • newsnow hotlist（按主题 2-gram 匹配热点，broad 模式，标题/热度）
      • 合并 candidate_news + source_refs（统一溯源）
  → deep_analysis（深度解读）
  → blog_writer（tech_depth 写作）
  → editor_in_chief（主编 + 事实核查）
  → 1 篇草稿（draft，metadata.run_id 关联 trace）
```

### article_retrieval 全源搜（新 custom 分支）
现有 strict（miniflux/wewe）+ broad（hotlist）两种。custom 合并：
1. 按 topic_keywords 搜 miniflux/wewe（`search_news_by_keywords`，深度文章）
2. 按 topic_hint 2-gram 搜 newsnow hotlist（`get_recent_hotlist_snapshots` + `_filter_hotlist`）
3. 合并去重 → candidate_news（深度 + 热点），source_refs 统一

### run_custom_topic_generation(topic_hint)【新增·graph.py】
- 跳过 `_discover_topics`（用户主题已定）
- `graph.ainvoke({skip_topic_discovery: True, topic_hint, topic_keywords: [topic_hint], style: "tech_depth"})`
- 1 篇 draft + trace run_id（复用 record_run_start/end + contextvar）
- 异步（threading，handler 触发，立即返回 run_id）

### API【新增】
- `POST /blog/generate-custom?topic=...` → `{run_id}`（异步，前端轮询 trace）
- handler `generate_custom(topic)`：record_run_start + threading → run_custom_topic_generation(run_id) + 返回 run_id

### 前端【改 BlogDraft.tsx】
- 加主题输入框 + "生成"按钮（与 3 专题按钮并列）
- 点击 → POST generate-custom?topic=输入 → 拿 run_id → 复用 handleGenerate 的轮询 trace 逻辑（liveTrace 进度）→ 1 draft
- 草稿 metadata.topic = "custom"（前端可区分）

### 复用（现成）
deep_analysis / blog_writer / editor_in_chief / image_picker(deferred to approve) / trace 全套 / 异步 threading + 轮询。

---

## 3. 实施顺序
1. `article_retrieval.py`：加全源搜函数（miniflux/wewe + newsnow 合并）
2. `graph.py`：`run_custom_topic_generation(topic_hint, run_id=None)`
3. `blog_handler.py` + `blog_router.py`：`generate_custom` + `POST /blog/generate-custom`
4. `BlogDraft.tsx`：主题输入框 + 按钮（复用轮询）
5. 验证：输入主题 → 全源搜 → 1 篇 + trace + 溯源

---

## 4. 涉及文件
- 改：`backend/src/domain/market/intel/blog/processors/article_retrieval.py`（全源搜）
- 改：`backend/src/domain/market/intel/blog/agents/graph.py`（run_custom_topic_generation）
- 改：`backend/src/api/handler/blog_handler.py` + `router/blog_router.py`
- 改：`frontend/apps/web/src/pages/BlogDraft.tsx`（输入框 + 按钮）
