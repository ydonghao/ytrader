# 预警中心统一收件箱（闭环增强·收官）设计 spec

日期：2026-09-27
前置：价格/指标告警与论点事件各有分区；本项合并为单一时间流。

## 1. 目标

预警中心顶部一个"统一收件箱"：价格告警（已触发）+ 指标告警（已触发）
+ 论点事件，按时间倒序合并展示——一眼看全"最近发生了什么"。
非目标：不新增已读体系（论点事件沿用既有 read 开关，价格/指标只读展示）。

## 2. API

`GET /alerts/unified?limit=50`：
- 价格：`{kind:'price', symbol, message: "上穿/下穿 X", time: triggered_at}`
- 指标：`{kind:'metric', symbol, message: "pe_ttm above 30", time}`
- 论点：`{kind:'thesis', symbol, message: 事件人话（重估verdict/破位/到价/排雷）,
  time, read, event_id}`
三源各取 limit 内，合并按 time 倒序截断。任一源失败降级为空不阻塞。

## 3. 前端

Alerts 页顶部"统一收件箱（近 N 条）"表：时间/类型徽章/标的/消息；
论点行可点"已读"（沿用 PUT /thesis/events/{id}/read）。

## 4. 测试与验收

端点：mock 三源（含一源抛错降级）；前端 build 通过。
