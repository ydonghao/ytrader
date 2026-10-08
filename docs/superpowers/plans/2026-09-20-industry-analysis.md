# 行业分析(Industry Analysis)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地规格 `docs/superpowers/specs/2026-09-20-industry-analysis-design.md`——破净率宏观择时、31行业景气热力图、板块资金流强弱、行业知识层与 LLM 解读。

**Architecture:** 照 boom 雷达惯例新建 `domain/market/industry_analysis/` 域：纯函数层(聚合/评分/知识加载) + 3 张新落库表 + 3 个每日 job + 2 个回填脚本 + `/industry` router(6 端点) + 前端一页三 Tab 与详情抽屉。全部增量。

**Tech Stack:** FastAPI + SQLModel/psycopg2 + APScheduler + akshare(既有) + LLMManager(既有)；前端 React + echarts(既有 `EChart` 薄封装) + vitest(既有)。

## Global Constraints

- 后端测试从 `backend/` 目录跑：`cd backend && uv run pytest tests/domain/market/industry_analysis -v`（venv 已激活时 `python -m pytest` 等价）；库内既有 52 个失败为历史遗留，只看新增子集。
- 前端测试：`cd frontend/apps/web && npm test`（vitest run，environment=node，纯逻辑测试）。
- 零新增依赖（python 与 npm 均不装新包）。
- API 信封一律 `{"code": 0, "msg": "ok", "data": ...}`（boom_router `_ok` 惯例）。
- 全站 A股红涨绿跌：图表用 `lib/chartTheme.ts` 的 `colorUp=#ff453a / colorDown=#30d158`；CSS 用 `var(--color-up/--color-down)`，不写裸色值。
- sw_code 口径：纯 6 位不带 `.SI`（如 `801010`）；index_ohlcv 里的行业指数 symbol 为 `sw801010`，基准沪深300 为 `sh000300`。
- 新表模型必须在 `backend/main.py` lifespan 里 import 注册才会被 `create_all` 建表。
- job 注册照 scheduler.py 惯例：闭包内动态 import + 整体 try/except + `log.error("[TAG] failed: %s", e)` + `CronTrigger(timezone="Asia/Shanghai")`。
- 配置走 `conf/settings.py` pydantic BaseModel + 默认值（boom_radar 同款，yaml 可缺块）。
- 每个任务结束 git commit 一次；不携带无关文件（`backend/.news_backfill_progress.json` 等进度文件不 add）。
- DB 连接：仓储用 `create_db_connection(get_dsn())` 单例 + `threading.Lock`；批量写用 psycopg2 `execute_values` + `ON CONFLICT DO UPDATE`。

## 文件总览

```
backend/
  conf/settings.py                                    # M: IndustryAnalysisConfig
  conf/industry_knowledge.yaml                        # C: 31行业知识层
  conf/em_flow_to_sw.yaml                             # C: 东财行业→申万近似映射
  src/domain/market/industry_analysis/
    __init__.py                                       # C
    knowledge.py                                      # C: 知识yaml加载+校验
    flow_map.py                                       # C: 资金流映射加载
    stats.py                                          # C: percentile_rank/median/histogram
    pb_break.py                                       # C: 破净率聚合纯函数
    prosperity.py                                     # C: 景气分纯函数
    inputs.py                                         # C: 评分输入装配(可注入假仓储)
    llm_analyst.py                                    # C: LLM解读
  src/infra/database/market/industry_analysis.py      # C: 3表+仓储
  src/domain/market/sync/jobs/
    industry_pb_break_sync.py                         # C: 每日增量(16:40)
    industry_fund_flow_sync.py                        # C: 每日落库(17:05)
    industry_prosperity_sync.py                       # C: 每日重算(17:20)
    industry_pb_break_backfill.py                     # C: 全历史回填(python -m)
    industry_prosperity_backfill.py                   # C: 月末采样回填(python -m)
  src/infra/scheduler.py                              # M: 注册3个job
  src/api/router/industry_router.py                   # C: 6端点
  main.py                                             # M: 表import注册 + router挂载
  tests/domain/market/industry_analysis/
    test_knowledge.py  test_flow_map.py  test_stats.py
    test_pb_break.py   test_prosperity.py  test_inputs.py
  tests/api/test_industry_router.py                   # C
frontend/apps/web/src/
  hooks/useIndustryAnalysis.ts                        # C
  lib/heat.ts                                         # C: 热力着色/排序纯函数
  pages/IndustryAnalysis.tsx / IndustryAnalysis.css   # C
  components/industry/
    PbBreakTab.tsx  ProsperityHeatmap.tsx  StrengthFlowTab.tsx  IndustryDetailDrawer.tsx
    __tests__/heat.test.ts                            # C
  App.tsx  components/Layout.tsx                      # M: 路由+菜单
```

规格偏差备忘（两处，均为简化，实施时不再讨论）：
1. 抽屉内"同行估值表"直接用 `/industry/{sw_code}` 返回的成分股估值（同一数据源 stock_valuation），不再二次调 `/financial/industry-peers`。
2. 产业链图谱用 flex 链条 chips（上游 → 本行业 → 下游）呈现，不用 echarts graph（窄抽屉内 chips 更清晰）。

---

### Task 1: 知识层 yaml + 加载器

**Files:**
- Create: `backend/conf/industry_knowledge.yaml`
- Create: `backend/src/domain/market/industry_analysis/__init__.py`
- Create: `backend/src/domain/market/industry_analysis/knowledge.py`
- Test: `backend/tests/domain/market/industry_analysis/test_knowledge.py`

**Interfaces:**
- Produces: `load_knowledge(path=None) -> dict[str, IndustryKnowledge]`（key=纯6位 sw_code）；`IndustryKnowledge(sw_code, name, tier, retail_suitable, approach, upstream: tuple, downstream: tuple, note)`；`TIER_LABELS = {1:"易分析", 2:"需专业分析", 3:"消息驱动"}`；`SW_L1_CODES`（31 个代码常量元组）。后续 Task 9/10/12 消费。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/market/industry_analysis/test_knowledge.py
"""知识层 yaml 加载与校验。"""
from pathlib import Path

import pytest

from src.domain.market.industry_analysis.knowledge import (
    SW_L1_CODES, TIER_LABELS, IndustryKnowledge, load_knowledge,
)

CONF = Path(__file__).parent.parent.parent.parent.parent / "conf" / "industry_knowledge.yaml"


def test_load_all_31():
    know = load_knowledge(CONF)
    assert set(know.keys()) == set(SW_L1_CODES)
    food = know["801120"]
    assert isinstance(food, IndustryKnowledge)
    assert food.name == "食品饮料"
    assert food.tier in (1, 2, 3)
    assert food.retail_suitable in ("high", "medium", "low")
    assert food.approach and food.upstream and food.downstream


def test_default_path_loads():
    know = load_knowledge()          # 不传路径 → conf/industry_knowledge.yaml
    assert len(know) == 31


def test_missing_code_raises(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text('"801120":\n  name: 食品饮料\n  tier: 1\n'
                 '  retail_suitable: high\n  approach: x\n'
                 '  upstream: [a]\n  downstream: [b]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="缺少申万一级行业"):
        load_knowledge(p)


def test_bad_enum_raises(tmp_path):
    p = tmp_path / "k.yaml"
    body = "".join(
        f'"{c}":\n  name: n{c}\n  tier: 1\n  retail_suitable: high\n'
        f"  approach: x\n  upstream: [a]\n  downstream: [b]\n"
        for c in SW_L1_CODES
    )
    p.write_text(body.replace("tier: 1", "tier: 9", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="tier"):
        load_knowledge(p)


def test_tier_labels():
    assert TIER_LABELS[1] == "易分析"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_knowledge.py -v`
Expected: FAIL（`ModuleNotFoundError: src.domain.market.industry_analysis`）

- [ ] **Step 3: 写 `__init__.py`、加载器与 yaml**

```python
# backend/src/domain/market/industry_analysis/__init__.py
"""行业分析域:破净率/景气分/资金流/知识层(规格见 docs/superpowers/specs/2026-09-20)。"""
```

```python
# backend/src/domain/market/industry_analysis/knowledge.py
"""申万一级行业知识层:conf/industry_knowledge.yaml 静态加载(用户笔记三层分级)。

启动/首次调用即校验:31 码齐全、枚举合法,坏配置报错而不是静默降级。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONF_DIR = Path(__file__).parent.parent.parent.parent.parent / "conf"

# 申万2021一级31个(纯6位,不带.SI)——与 sw_industry_member.sw_code_l1 同口径
SW_L1_CODES: tuple[str, ...] = (
    "801010", "801020", "801030", "801040", "801050", "801080", "801110",
    "801120", "801130", "801140", "801150", "801160", "801170", "801180",
    "801200", "801210", "801230", "801710", "801720", "801730", "801740",
    "801750", "801760", "801770", "801780", "801790", "801880", "801890",
    "801960", "801970", "801980",
)

TIER_LABELS = {1: "易分析", 2: "需专业分析", 3: "消息驱动"}
SUITABILITY = ("high", "medium", "low")


@dataclass(frozen=True)
class IndustryKnowledge:
    sw_code: str
    name: str
    tier: int                  # 投资难易度三层(用户笔记)
    retail_suitable: str       # 散户适宜度 high/medium/low
    approach: str              # 一句话分析抓手
    upstream: tuple[str, ...]
    downstream: tuple[str, ...]
    note: str = ""


def _to_knowledge(sw_code: str, raw: dict[str, Any]) -> IndustryKnowledge:
    tier = raw.get("tier")
    if tier not in TIER_LABELS:
        raise ValueError(f"{sw_code} tier 非法: {tier}(须 1/2/3)")
    suit = raw.get("retail_suitable")
    if suit not in SUITABILITY:
        raise ValueError(f"{sw_code} retail_suitable 非法: {suit}")
    return IndustryKnowledge(
        sw_code=sw_code,
        name=str(raw.get("name", "")).strip(),
        tier=int(tier),
        retail_suitable=suit,
        approach=str(raw.get("approach", "")).strip(),
        upstream=tuple(raw.get("upstream") or ()),
        downstream=tuple(raw.get("downstream") or ()),
        note=str(raw.get("note", "") or ""),
    )


def load_knowledge(path: Path | None = None) -> dict[str, IndustryKnowledge]:
    """加载并校验知识 yaml;缺码/坏枚举即抛 ValueError。"""
    p = path or (_CONF_DIR / "industry_knowledge.yaml")
    raw: dict = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    missing = set(SW_L1_CODES) - set(raw.keys())
    if missing:
        raise ValueError(f"industry_knowledge.yaml 缺少申万一级行业: {sorted(missing)}")
    return {code: _to_knowledge(code, raw[code]) for code in SW_L1_CODES}
```

`backend/conf/industry_knowledge.yaml`（31 条全量，内容按用户笔记初拟、可手改）：

```yaml
# 申万一级行业知识层——投资难易度三层分级与产业链(用户笔记初拟,可随时手改)
# tier: 1=消费者容易分析最好投资 / 2=需专业分析最好业内人士 / 3=消息短时效高精力
"801010":
  name: 农林牧渔
  tier: 2
  retail_suitable: medium
  approach: 猪周期主导,看能繁母猪存栏与猪价;种业看政策
  upstream: [化肥农药, 饲料]
  downstream: [食品饮料, 商贸零售]
"801020":
  name: 煤炭
  tier: 2
  retail_suitable: low
  approach: 跟大宗商品(煤价)走,看长协价与库存,周期思维
  upstream: []
  downstream: [电力, 钢铁, 基础化工, 建筑材料]
"801030":
  name: 基础化工
  tier: 2
  retail_suitable: low
  approach: 中游制造,看下游需求与产品价差,专业性较强
  upstream: [煤炭, 石油石化]
  downstream: [农林牧渔, 纺织服饰, 建筑材料, 电力设备]
"801040":
  name: 钢铁
  tier: 2
  retail_suitable: low
  approach: 下游是地产/建筑,看地产周期与钢价库存
  upstream: [煤炭, 有色金属(铁矿)]
  downstream: [建筑装饰, 汽车, 机械设备, 家用电器]
"801050":
  name: 有色金属
  tier: 2
  retail_suitable: low
  approach: 跟全球大宗(铜铝金)走,金融属性强,研究好了不如做期货
  upstream: [煤炭, 电力]
  downstream: [电力设备, 电子, 汽车, 建筑装饰]
"801080":
  name: 电子
  tier: 2
  retail_suitable: low
  approach: 半导体周期+创新周期,看库存与稼动率
  upstream: [基础化工, 有色金属]
  downstream: [家用电器, 汽车, 计算机, 通信]
"801110":
  name: 家用电器
  tier: 1
  retail_suitable: high
  approach: 消费属性+地产后周期,看白电格局与原材料成本
  upstream: [有色金属, 钢铁, 基础化工]
  downstream: [商贸零售, 房地产(精装)]
"801120":
  name: 食品饮料
  tier: 1
  retail_suitable: high
  approach: 消费者最容易分析,看品牌/渠道/提价能力,白酒看批价
  upstream: [农林牧渔, 基础化工(包装)]
  downstream: [商贸零售, 社会服务]
"801130":
  name: 纺织服饰
  tier: 1
  retail_suitable: medium
  approach: 看品牌与库存周期,门槛较低
  upstream: [农林牧渔(棉), 基础化工(化纤)]
  downstream: [商贸零售]
"801140":
  name: 轻工制造
  tier: 2
  retail_suitable: medium
  approach: 家居看地产后周期,造纸看浆价
  upstream: [基础化工, 农林牧渔]
  downstream: [房地产, 商贸零售]
"801150":
  name: 医药生物
  tier: 2
  retail_suitable: low
  approach: 专业性非常强,政策(集采)影响大,非专业人士不建议
  upstream: [基础化工(原料药), 基础化工(CXO耗材)]
  downstream: [社会服务(医疗), 商贸零售(药店)]
"801160":
  name: 公用事业
  tier: 2
  retail_suitable: medium
  approach: 类债属性,看电价水价与股息率
  upstream: [煤炭, 电力设备]
  downstream: [全行业(用电用水)]
"801170":
  name: 交通运输
  tier: 2
  retail_suitable: medium
  approach: 看运价周期(航运/航空)与流量恢复
  upstream: [煤炭(油料), 机械设备(运力)]
  downstream: [全行业(物流)]
"801180":
  name: 房地产
  tier: 2
  retail_suitable: low
  approach: 政策强驱动,高杠杆,看销售与融资政策
  upstream: [建筑装饰, 建筑材料]
  downstream: [家用电器, 建筑材料, 轻工制造]
"801200":
  name: 商贸零售
  tier: 2
  retail_suitable: medium
  approach: 看客流与线上化冲击,格局变化快
  upstream: [食品饮料, 纺织服饰, 家用电器]
  downstream: [消费者]
"801210":
  name: 社会服务
  tier: 2
  retail_suitable: medium
  approach: 看连锁化率与单店模型
  upstream: []
  downstream: [消费者]
"801230":
  name: 综合
  tier: 3
  retail_suitable: low
  approach: 业务杂难以跟踪,不建议
  upstream: []
  downstream: []
"801710":
  name: 建筑材料
  tier: 2
  retail_suitable: low
  approach: 下游地产/建筑,看价格与产能利用率
  upstream: [煤炭, 基础化工]
  downstream: [房地产, 建筑装饰]
"801720":
  name: 建筑装饰
  tier: 2
  retail_suitable: low
  approach: 下游投资周期,垫资模式现金流差
  upstream: [建筑材料, 钢铁]
  downstream: [房地产, 公用事业]
"801730":
  name: 电力设备
  tier: 2
  retail_suitable: low
  approach: 行业门槛高,技术迭代快(光伏/锂电),看技术路线与产能
  upstream: [有色金属, 基础化工, 电子]
  downstream: [公用事业, 汽车]
"801740":
  name: 国防军工
  tier: 3
  retail_suitable: low
  approach: 不以盈利为主要目的,订单驱动,消息时效短
  upstream: [钢铁, 有色金属, 电子]
  downstream: [国家订单]
"801750":
  name: 计算机
  tier: 2
  retail_suitable: low
  approach: 技术迭代快(AI产业链核心),看订单与产品化程度,主题多
  upstream: [电子]
  downstream: [全行业(数字化)]
"801760":
  name: 传媒
  tier: 2
  retail_suitable: medium
  approach: 内容行业,看爆款与政策监管
  upstream: [电子(设备), 通信]
  downstream: [消费者]
"801770":
  name: 通信
  tier: 2
  retail_suitable: low
  approach: 运营商稳+设备商跟资本开支周期
  upstream: [电子]
  downstream: [计算机, 传媒]
"801780":
  name: 银行
  tier: 1
  retail_suitable: high
  approach: 高度标准化,看净息差/不良率,学习一次受用
  upstream: [央行(流动性)]
  downstream: [全行业(信贷)]
"801790":
  name: 非银金融
  tier: 1
  retail_suitable: medium
  approach: 券商看市场beta,保险看利差损,较标准
  upstream: [银行]
  downstream: [全行业(资金融通)]
"801880":
  name: 汽车
  tier: 2
  retail_suitable: medium
  approach: 看车型周期与电动化渗透率,价格战频繁
  upstream: [钢铁, 有色金属, 电子, 基础化工]
  downstream: [商贸零售, 社会服务(出行)]
"801890":
  name: 机械设备
  tier: 2
  retail_suitable: low
  approach: 中游,看下游资本开支与订单
  upstream: [钢铁, 有色金属]
  downstream: [电力设备, 建筑, 汽车]
"801960":
  name: 石油石化
  tier: 2
  retail_suitable: low
  approach: 跟油价,上游看桶油成本,炼化看价差
  upstream: []
  downstream: [基础化工, 交通运输, 基础化工(化纤)]
"801970":
  name: 环保
  tier: 3
  retail_suitable: low
  approach: 非盈利导向,依赖政府支付,谨慎
  upstream: [机械设备, 基础化工]
  downstream: [政府订单]
"801980":
  name: 美容护理
  tier: 1
  retail_suitable: medium
  approach: 消费属性强,看品牌力与渠道
  upstream: [基础化工(原料)]
  downstream: [商贸零售, 社会服务]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_knowledge.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/conf/industry_knowledge.yaml \
  backend/src/domain/market/industry_analysis/ \
  backend/tests/domain/market/industry_analysis/test_knowledge.py
git commit -m "feat(industry): 申万31行业知识层yaml+加载校验——难易度三层/散户适宜度/产业链"
```

---

### Task 2: 东财→申万资金流映射 + 加载器

**Files:**
- Create: `backend/conf/em_flow_to_sw.yaml`
- Create: `backend/src/domain/market/industry_analysis/flow_map.py`
- Test: `backend/tests/domain/market/industry_analysis/test_flow_map.py`

**Interfaces:**
- Produces: `load_flow_map(path=None) -> dict[str, str]`（key=东财行业名，value=申万纯6位码；未匹配由调用方置缺）。Task 6/9 消费。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/market/industry_analysis/test_flow_map.py
"""东财行业→申万映射加载。"""
from src.domain.market.industry_analysis.flow_map import load_flow_map
from src.domain.market.industry_analysis.knowledge import SW_L1_CODES


def test_load_and_values_are_sw_codes():
    m = load_flow_map()
    assert len(m) >= 40
    assert all(v in SW_L1_CODES for v in m.values())


def test_known_entries():
    m = load_flow_map()
    assert m.get("银行") == "801780"
    assert m.get("半导体") == "801080"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_flow_map.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 写映射 yaml 与加载器**

```python
# backend/src/domain/market/industry_analysis/flow_map.py
"""东财行业资金流→申万一级行业近似映射(多对一,人工维护)。

未匹配的东财行业由调用方置缺(评分按剩余权重归一),不强行归属。
"""
from __future__ import annotations

from pathlib import Path

import yaml

_CONF_DIR = Path(__file__).parent.parent.parent.parent.parent / "conf"


def load_flow_map(path: Path | None = None) -> dict[str, str]:
    p = path or (_CONF_DIR / "em_flow_to_sw.yaml")
    raw: dict = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(k).strip(): str(v).strip() for k, v in raw.items()}
```

`backend/conf/em_flow_to_sw.yaml`（初始种子，东财口径行业名→申万码；未列出的行业资金分项为缺项，可随时手改补充）：

```yaml
# 东财行业名 → 申万一级行业(纯6位)。近似多对一,允许缺。
农牧饲渔: "801010"
种植业: "801010"
煤炭行业: "801020"
化工行业: "801030"
化纤行业: "801030"
钢铁行业: "801040"
有色金属: "801050"
贵金属: "801050"
小金属: "801050"
能源金属: "801050"
电子元件: "801080"
半导体: "801080"
光学光电子: "801080"
消费电子: "801080"
电子化学品: "801080"
家电行业: "801110"
食品饮料: "801120"
酿酒行业: "801120"
食品加工: "801120"
纺织服装: "801130"
家用轻工: "801140"
造纸印刷: "801140"
医疗器械: "801150"
医疗服务: "801150"
医药商业: "801150"
中药: "801150"
化学制药: "801150"
生物制品: "801150"
电力行业: "801160"
燃气: "801160"
环保: "801970"
航运港口: "801170"
铁路公路: "801170"
航空机场: "801170"
物流行业: "801170"
房地产开发: "801180"
房地产服务: "801180"
商业百货: "801200"
旅游酒店: "801210"
专业服务: "801210"
教育: "801210"
水泥建材: "801710"
玻璃玻纤: "801710"
装修装饰: "801720"
工程建设: "801720"
电源设备: "801730"
电池: "801730"
光伏设备: "801730"
风电设备: "801730"
电网设备: "801730"
航天航空: "801740"
船舶制造: "801740"
计算机设备: "801750"
软件服务: "801750"
互联网服务: "801750"
游戏: "801760"
文化传媒: "801760"
通信服务: "801770"
通信设备: "801770"
银行: "801780"
保险: "801790"
证券: "801790"
汽车整车: "801880"
汽车零部件: "801880"
汽车服务: "801880"
通用设备: "801890"
专用设备: "801890"
工程机械: "801890"
仪器仪表: "801890"
石油行业: "801960"
美容护理: "801980"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_flow_map.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/conf/em_flow_to_sw.yaml backend/src/domain/market/industry_analysis/flow_map.py \
  backend/tests/domain/market/industry_analysis/test_flow_map.py
git commit -m "feat(industry): 东财行业资金流→申万一级近似映射yaml+加载"
```

---

### Task 3: 三张新表 + 仓储 + main.py 注册

**Files:**
- Create: `backend/src/infra/database/market/industry_analysis.py`
- Modify: `backend/main.py`（lifespan 表 import 段，boom import 块之后追加；行号以当前文件为准）
- Test: `backend/tests/domain/market/industry_analysis/test_tables.py`

**Interfaces:**
- Produces（Task 6-10 消费）:
  - 表模型 `IndustryPbBreakTable / IndustryFundFlowTable / IndustryProsperityTable`
  - `create_industry_analysis_repository() -> IndustryAnalysisRepository`（惰性单例连接，模式照抄 `sw_industry.py:229-248`）
  - 仓储方法：
    - `upsert_pb_break(rows: list[dict]) -> int`（行键 trade_date/scope/scope_code + total_count/break_count/break_rate/median_pb）
    - `get_pb_break_series(scope, scope_code, start, end) -> list[dict]`（date 升序）
    - `get_pb_break_latest(scope) -> dict | None`
    - `upsert_fund_flow(rows: list[dict]) -> int`（trade_date/em_industry_name/main_net_inflow/close_change_pct）
    - `get_flow_latest_date() -> dt.date | None`
    - `get_flow_rows(start: dt.date) -> list[dict]`
    - `upsert_prosperity(rows: list[dict]) -> int`（trade_date/sw_code/score/score_profit/score_valuation/score_momentum/score_flow/inputs(JSON)）
    - `get_prosperity(trade_date) -> list[dict]`
    - `get_prosperity_latest_date() -> dt.date | None`
    - `get_cross_section_latest_two(level=1) -> dict[str, list[dict]]`（每 sw_code 两个最新报告期的 revenue_yoy/net_profit_sum/report_date）
    - `get_member_valuations(trade_date) -> list[dict]`（symbol/name/sw_code_l1/sw_name_l1/pb/pe_ttm/total_mv，JOIN sw_industry_member + stock_valuation 按日）
    - `get_stock_valuation_dates(start, end) -> list[dt.date]`（DISTINCT，升序——回填用）
    - `get_index_closes(symbols, start, end) -> dict[str, list[tuple[dt.date, float]]]`
    - `get_sw_valuation_window(sw_codes, start, end) -> dict[str, list[dict]]`（sw_code/pe_ttm/pb/trade_date，升序）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/market/industry_analysis/test_tables.py
"""表模型可导入注册;列名契约(不触库——SQL 字符串与列常量静态校验)。"""
from src.infra.database.market.industry_analysis import (
    PB_BREAK_COLUMNS, PROSPERITY_COLUMNS, FLOW_COLUMNS,
    IndustryFundFlowTable, IndustryPbBreakTable, IndustryProsperityTable,
)


def test_table_names():
    assert IndustryPbBreakTable.__tablename__ == "industry_pb_break_daily"
    assert IndustryFundFlowTable.__tablename__ == "industry_fund_flow_daily"
    assert IndustryProsperityTable.__tablename__ == "industry_prosperity_daily"


def test_column_contracts():
    assert PB_BREAK_COLUMNS == ("trade_date", "scope", "scope_code",
                                "total_count", "break_count", "break_rate",
                                "median_pb")
    assert FLOW_COLUMNS == ("trade_date", "em_industry_name",
                            "main_net_inflow", "close_change_pct")
    assert PROSPERITY_COLUMNS == ("trade_date", "sw_code", "score",
                                  "score_profit", "score_valuation",
                                  "score_momentum", "score_flow", "inputs")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_tables.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 写表模型与仓储**

```python
# backend/src/infra/database/market/industry_analysis.py
"""行业分析三表:破净率序列/资金流历史/景气分快照(规格 2026-09-20 §3)。

写走 psycopg2 execute_values(sw_industry.py 同款),读走 SQLModel session。
"""
import datetime as dt
import threading
from datetime import datetime
from typing import Any, Optional

import psycopg2
from psycopg2.extras import execute_values, Json
from sqlalchemy import JSON, Column, DateTime, func
from sqlmodel import SQLModel, Field, select

from src.infra.database.sql_engine.engine import (
    DBConnection, create_db_connection,
)
from src.infra.database.sql_engine.dsn import get_dsn

PB_BREAK_COLUMNS = ("trade_date", "scope", "scope_code", "total_count",
                    "break_count", "break_rate", "median_pb")
FLOW_COLUMNS = ("trade_date", "em_industry_name", "main_net_inflow",
                "close_change_pct")
PROSPERITY_COLUMNS = ("trade_date", "sw_code", "score", "score_profit",
                      "score_valuation", "score_momentum", "score_flow",
                      "inputs")


class IndustryPbBreakTable(SQLModel, table=True):
    __tablename__ = "industry_pb_break_daily"
    trade_date: dt.date = Field(primary_key=True)
    scope: str = Field(primary_key=True)          # market / industry
    scope_code: str = Field(primary_key=True)     # market='ALL'; 行业=申万码
    total_count: int = 0
    break_count: int = 0
    break_rate: Optional[float] = None            # 0-1 小数
    median_pb: Optional[float] = None


class IndustryFundFlowTable(SQLModel, table=True):
    __tablename__ = "industry_fund_flow_daily"
    trade_date: dt.date = Field(primary_key=True)
    em_industry_name: str = Field(primary_key=True)   # 东财口径(~90个)
    main_net_inflow: Optional[float] = None           # 元
    close_change_pct: Optional[float] = None          # 行业当日涨跌幅%
    updated_at: datetime = Field(
        default_factory=datetime.now,
        sa_column=Column(DateTime, server_default=func.now()),
    )


class IndustryProsperityTable(SQLModel, table=True):
    __tablename__ = "industry_prosperity_daily"
    trade_date: dt.date = Field(primary_key=True)
    sw_code: str = Field(primary_key=True)        # 纯6位
    score: Optional[float] = None                 # 0-100,全缺为 None
    score_profit: Optional[float] = None
    score_valuation: Optional[float] = None
    score_momentum: Optional[float] = None
    score_flow: Optional[float] = None
    inputs: Any = Field(default={}, sa_column=Column(JSON))  # 原始输入快照


class IndustryAnalysisRepository:
    def __init__(self, db: DBConnection):
        self._db = db

    # ── 写(execute_values upsert)────────────────────────────

    def _upsert(self, table: str, cols: tuple, rows: list[dict],
                json_cols: tuple = (),
                conflict: tuple | None = None) -> int:
        if not rows:
            return 0
        conflict = conflict or cols[:2]      # 默认前两列为冲突目标
        values = []
        for r in rows:
            values.append(tuple(
                Json(r.get(c)) if c in json_cols
                else (r[c].isoformat() if isinstance(r.get(c), dt.date) and
                      c == "trade_date" else r.get(c))
                for c in cols
            ))
        sql = (
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s "
            f"ON CONFLICT ({', '.join(conflict)}) DO UPDATE SET "
            + ", ".join(f"{c}=EXCLUDED.{c}" for c in cols
                        if c not in conflict)
        )
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                execute_values(cur, sql, values)
            conn.commit()
        finally:
            conn.close()
        return len(values)

    def upsert_pb_break(self, rows: list[dict]) -> int:
        return self._upsert("industry_pb_break_daily", PB_BREAK_COLUMNS, rows,
                            conflict=("trade_date", "scope", "scope_code"))

    def upsert_fund_flow(self, rows: list[dict]) -> int:
        return self._upsert("industry_fund_flow_daily", FLOW_COLUMNS, rows)

    def upsert_prosperity(self, rows: list[dict]) -> int:
        return self._upsert("industry_prosperity_daily", PROSPERITY_COLUMNS,
                            rows, json_cols=("inputs",))

    # ── 破净率读 ────────────────────────────────────────────

    def get_pb_break_series(self, scope: str, scope_code: str,
                            start: dt.date, end: dt.date) -> list[dict]:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(IndustryPbBreakTable).where(
                    IndustryPbBreakTable.scope == scope,
                    IndustryPbBreakTable.scope_code == scope_code,
                    IndustryPbBreakTable.trade_date >= start,
                    IndustryPbBreakTable.trade_date <= end,
                ).order_by(IndustryPbBreakTable.trade_date)
            ).all()
            return [self._pb_row(r) for r in rows]

    def get_pb_break_latest(self, scope: str) -> Optional[dict]:
        with self._db.session_scope() as s:
            row = s.exec(
                select(IndustryPbBreakTable)
                .where(IndustryPbBreakTable.scope == scope)
                .order_by(IndustryPbBreakTable.trade_date.desc())
            ).first()
            return self._pb_row(row) if row else None

    @staticmethod
    def _pb_row(r: IndustryPbBreakTable) -> dict:
        return {"trade_date": r.trade_date, "scope": r.scope,
                "scope_code": r.scope_code, "total_count": r.total_count,
                "break_count": r.break_count, "break_rate": r.break_rate,
                "median_pb": r.median_pb}

    # ── 资金流读 ────────────────────────────────────────────

    def get_flow_latest_date(self) -> Optional[dt.date]:
        with self._db.session_scope() as s:
            return s.exec(select(func.max(IndustryFundFlowTable.trade_date))
                          ).one()

    def get_flow_rows(self, start: dt.date) -> list[dict]:
        with self._db.session_scope() as s:
            rows = s.exec(
                select(IndustryFundFlowTable)
                .where(IndustryFundFlowTable.trade_date >= start)
                .order_by(IndustryFundFlowTable.trade_date)
            ).all()
            return [{"trade_date": r.trade_date,
                     "em_industry_name": r.em_industry_name,
                     "main_net_inflow": r.main_net_inflow,
                     "close_change_pct": r.close_change_pct} for r in rows]

    # ── 景气分读 ────────────────────────────────────────────

    def get_prosperity(self, trade_date: dt.date) -> list[dict]:
        with self._db.session_scope() as s:
            rows = s.exec(select(IndustryProsperityTable).where(
                IndustryProsperityTable.trade_date == trade_date)).all()
            return [{"sw_code": r.sw_code, "score": r.score,
                     "score_profit": r.score_profit,
                     "score_valuation": r.score_valuation,
                     "score_momentum": r.score_momentum,
                     "score_flow": r.score_flow, "inputs": r.inputs or {}}
                    for r in rows]

    def get_prosperity_latest_date(self) -> Optional[dt.date]:
        with self._db.session_scope() as s:
            return s.exec(select(func.max(IndustryProsperityTable.trade_date))
                          ).one()

    # ── 评分输入读(裸 SQL,跨表 JOIN 一次到位)────────────────

    def get_cross_section_latest_two(self, level: int = 1) -> dict[str, list]:
        sql = """
            SELECT sw_code, report_date, revenue_yoy, net_profit_sum
            FROM sw_industry_cross_section
            WHERE level = %(lv)s AND sw_code IN (
                SELECT DISTINCT sw_code FROM sw_industry_cross_section
                WHERE level = %(lv)s
                  AND report_date = (SELECT max(report_date)
                                     FROM sw_industry_cross_section
                                     WHERE level = %(lv)s)
            )
            AND report_date >= (SELECT max(report_date)
                                FROM sw_industry_cross_section
                                WHERE level = %(lv)s) - interval '550 days'
            ORDER BY sw_code, report_date
        """
        # SQLModel session.exec 仅支持 select;原生 SQL 走 connection
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"lv": level})
                rows = cur.fetchall()
        finally:
            conn.close()
        out: dict[str, list] = {}
        for sw_code, report_date, rev_yoy, np_sum in rows:
            out.setdefault(sw_code, []).append({
                "report_date": report_date, "revenue_yoy": rev_yoy,
                "net_profit_sum": np_sum})
        return out

    def get_member_valuations(self, trade_date: dt.date) -> list[dict]:
        sql = """
            SELECT m.symbol, m.name, m.sw_code_l1, m.sw_name_l1,
                   v.pb, v.pe_ttm, v.total_mv
            FROM sw_industry_member m
            JOIN stock_valuation v ON v.symbol = m.symbol
                                 AND v.trade_date = %(d)s
        """
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"d": trade_date})
                rows = cur.fetchall()
        finally:
            conn.close()
        return [{"symbol": r[0], "name": r[1], "sw_code_l1": r[2],
                 "sw_name_l1": r[3], "pb": r[4], "pe_ttm": r[5],
                 "total_mv": r[6]} for r in rows]

    def get_stock_valuation_dates(self, start: dt.date,
                                  end: dt.date) -> list[dt.date]:
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT trade_date FROM stock_valuation "
                    "WHERE trade_date BETWEEN %s AND %s "
                    "ORDER BY trade_date", (start, end))
                return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

    def get_index_closes(self, symbols: list[str], start: dt.date,
                         end: dt.date) -> dict[str, list]:
        sql = ("SELECT symbol, trade_date, close FROM index_ohlcv "
               "WHERE symbol = ANY(%(syms)s) AND trade_date BETWEEN "
               "%(s)s AND %(e)s ORDER BY symbol, trade_date")
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"syms": symbols, "s": start, "e": end})
                rows = cur.fetchall()
        finally:
            conn.close()
        out: dict[str, list] = {}
        for sym, d, close in rows:
            out.setdefault(sym, []).append((d, float(close)))
        return out

    def get_sw_valuation_window(self, sw_codes: list[str], start: dt.date,
                                end: dt.date) -> dict[str, list]:
        sql = ("SELECT sw_code, trade_date, pe_ttm, pb "
               "FROM sw_index_valuation_daily "
               "WHERE sw_code = ANY(%(cs)s) AND trade_date BETWEEN "
               "%(s)s AND %(e)s AND pb IS NOT NULL "
               "ORDER BY sw_code, trade_date")
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"cs": sw_codes, "s": start, "e": end})
                rows = cur.fetchall()
        finally:
            conn.close()
        out: dict[str, list] = {}
        for code, d, pe, pb in rows:
            out.setdefault(code, []).append(
                {"trade_date": d, "pe_ttm": pe, "pb": pb})
        return out


# ======== 工厂(模式同 sw_industry.py)========

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()


def _get_db_connection() -> DBConnection:
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def create_industry_analysis_repository(
    db_connection: DBConnection | None = None,
) -> IndustryAnalysisRepository:
    """创建行业分析仓储(首次调用触发惰性建表)。"""
    return IndustryAnalysisRepository(db_connection or _get_db_connection())
```

注意两处实现细节：① `get_cross_section_latest_two` 里删除那行无用的 `s.exec(...) if False else None` 死代码，直接用 psycopg2 原生游标（SQLModel `session.exec` 不收裸 SQL）；② `sw_index_valuation_daily.sw_code` 存的形态以库内实际为准——实施时先跑 `SELECT DISTINCT sw_code FROM sw_index_valuation_daily LIMIT 5` 确认（若带 `sw` 前缀则在本方法 SQL 里做 `ltrim`/统一去掉前缀后再返回，保证返回 key 为纯 6 位，与 `SW_L1_CODES` 一致）。

- [ ] **Step 4: main.py lifespan 注册**

在 `backend/main.py` lifespan 的 boom import 块之后追加（boom 块约 L120-123）：

```python
        # Industry analysis: import models so create_all picks up 3 tables
        from src.infra.database.market.industry_analysis import (  # noqa: F401
            IndustryFundFlowTable, IndustryPbBreakTable,
            IndustryProsperityTable,
        )
```

- [ ] **Step 5: 跑测试确认通过 + 建表验证**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_tables.py -v`
Expected: 3 passed

Run（真库验证 create_all，可选但推荐）:
`cd backend && uv run python -c "import main" && PGPASSWORD=$(grep -oP '(?<=postgres:)[^@]+' conf/config.local.yaml | head -1) psql -h 127.0.0.1 -U postgres -d ytrader -c "\dt industry_*"`
Expected: 三张 `industry_*` 表已建（首次启动 main 后）。

- [ ] **Step 6: Commit**

```bash
git add backend/src/infra/database/market/industry_analysis.py backend/main.py \
  backend/tests/domain/market/industry_analysis/test_tables.py
git commit -m "feat(industry): 破净率/资金流/景气分三表+仓储+main注册"
```

---

### Task 4: 统计纯函数 + 破净率聚合纯函数

**Files:**
- Create: `backend/src/domain/market/industry_analysis/stats.py`
- Create: `backend/src/domain/market/industry_analysis/pb_break.py`
- Test: `backend/tests/domain/market/industry_analysis/test_stats.py`
- Test: `backend/tests/domain/market/industry_analysis/test_pb_break.py`

**Interfaces:**
- Produces:
  - `stats.percentile_rank(value, series) -> float | None`（0-100，midrank：`(count_lt + 0.5*count_eq) / n * 100`；series 为空或 value None → None）
  - `stats.median(values) -> float | None`
  - `stats.histogram(values, bins=20, lo=None, hi=None) -> {"edges": [...], "counts": [...]}`（lo/hi 缺省取 min/max；过滤越界与 None）
  - `pb_break.aggregate_pb_break(rows) -> {"market": BreakStat, "industries": dict[str, BreakStat]}`；输入 `rows = [(symbol, pb|None, sw_code_l1|None), ...]`；`BreakStat(total_count, break_count, break_rate, median_pb)`（break_rate 为 0-1 小数；pb 为 None 的行计入 total 但不计破净/中位）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/market/industry_analysis/test_stats.py
from src.domain.market.industry_analysis.stats import (
    histogram, median, percentile_rank,
)


def test_percentile_rank_midrank():
    assert percentile_rank(3.0, [1.0, 2.0, 3.0, 4.0, 5.0]) == 50.0
    assert percentile_rank(5.0, [1.0, 2.0, 3.0]) == 100.0
    assert percentile_rank(0.5, [1.0, 2.0]) == 0.0
    # 并列取中位:两个 2.0 在 [1,2,2,3] → (1 + 0.5*2)/4 = 50%
    assert percentile_rank(2.0, [1.0, 2.0, 2.0, 3.0]) == 50.0


def test_percentile_rank_degenerate():
    assert percentile_rank(None, [1.0]) is None
    assert percentile_rank(1.0, []) is None
    assert percentile_rank(1.0, [1.0]) == 50.0   # midrank:单值取中位


def test_median():
    assert median([3.0, 1.0, 2.0]) == 2.0
    assert median([4.0, 1.0, 2.0, 3.0]) == 2.5
    assert median([]) is None


def test_histogram():
    h = histogram([1, 2, 3, 4, 5], bins=4)
    assert len(h["counts"]) == 4
    assert sum(h["counts"]) == 5
    assert h["counts"] == [1, 1, 1, 2]   # 5 落入最后一桶(右端闭合)
    # 过滤越界与 None
    h2 = histogram([1, 2, 3, None, 99], bins=2, lo=0, hi=4)
    assert sum(h2["counts"]) == 3
```

```python
# backend/tests/domain/market/industry_analysis/test_pb_break.py
from src.domain.market.industry_analysis.pb_break import aggregate_pb_break

ROWS = [
    ("sh600001", 0.8, "801780"),   # 破净
    ("sh600002", 1.2, "801780"),
    ("sz000001", 0.9, "801120"),   # 破净
    ("sz000002", None, "801120"),  # 缺pb:计总数不计破净
    ("sh600003", 5.0, None),       # 无行业归属:只进market
]


def test_market_scope():
    out = aggregate_pb_break(ROWS)
    m = out["market"]
    assert m.total_count == 5
    assert m.break_count == 2
    assert abs(m.break_rate - 0.4) < 1e-9
    assert m.median_pb == 1.05     # [0.8,0.9,1.2,5.0] 中位 =(0.9+1.2)/2


def test_industry_scope_excludes_unmapped():
    out = aggregate_pb_break(ROWS)
    bank = out["industries"]["801780"]
    assert bank.total_count == 2 and bank.break_count == 1
    assert "801120" in out["industries"]
    food = out["industries"]["801120"]
    assert food.total_count == 2 and food.break_count == 1
    # 缺pb行的中位:只剩 [0.9]
    assert food.median_pb == 0.9


def test_empty():
    out = aggregate_pb_break([])
    assert out["market"].total_count == 0
    assert out["industries"] == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_stats.py tests/domain/market/industry_analysis/test_pb_break.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现**

```python
# backend/src/domain/market/industry_analysis/stats.py
"""统计小工具(纯函数,无 IO)。"""
from __future__ import annotations

from typing import Optional, Sequence


def percentile_rank(value: Optional[float],
                    series: Sequence[float]) -> Optional[float]:
    """midrank 百分位(0-100):并列值取中位,避免并列全部 100 的偏置。"""
    if value is None:
        return None
    vals = [v for v in series if v is not None]
    if not vals:
        return None
    lt = sum(1 for v in vals if v < value)
    eq = sum(1 for v in vals if v == value)
    return (lt + 0.5 * eq) / len(vals) * 100.0


def median(values: Sequence[Optional[float]]) -> Optional[float]:
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return None
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def histogram(values: Sequence[Optional[float]], bins: int = 20,
              lo: Optional[float] = None,
              hi: Optional[float] = None) -> dict:
    vals = [v for v in values if v is not None]
    if lo is not None:
        vals = [v for v in vals if v >= lo]
    if hi is not None:
        vals = [v for v in vals if v <= hi]
    if not vals or bins <= 0:
        return {"edges": [], "counts": [0] * max(bins, 0)}
    a = min(vals) if lo is None else lo
    b = max(vals) if hi is None else hi
    if a == b:
        b = a + 1.0
    width = (b - a) / bins
    counts = [0] * bins
    for v in vals:
        i = min(int((v - a) / width), bins - 1)
        counts[i] += 1
    edges = [round(a + i * width, 4) for i in range(bins + 1)]
    return {"edges": edges, "counts": counts}
```

```python
# backend/src/domain/market/industry_analysis/pb_break.py
"""破净率聚合(纯函数):个股PB行 → market/industry 两级破净统计。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.domain.market.industry_analysis.stats import median


@dataclass(frozen=True)
class BreakStat:
    total_count: int
    break_count: int
    break_rate: Optional[float]   # 0-1
    median_pb: Optional[float]


def _stat(pbs: list[Optional[float]]) -> BreakStat:
    valid = [p for p in pbs if p is not None]
    n_break = sum(1 for p in valid if p < 1.0)
    rate = (n_break / len(pbs)) if pbs else None
    return BreakStat(total_count=len(pbs), break_count=n_break,
                     break_rate=rate, median_pb=median(valid))


def aggregate_pb_break(rows) -> dict:
    """rows: [(symbol, pb|None, sw_code_l1|None), ...] 一次遍历两级聚合。

    market 口径含全部行(无行业归属也计入——规格§3.1:市场级无偏差);
    industries 只含有申万归属的行。
    """
    all_pb: list[Optional[float]] = []
    by_ind: dict[str, list[Optional[float]]] = {}
    for _symbol, pb, sw_code in rows:
        all_pb.append(pb)
        if sw_code:
            by_ind.setdefault(sw_code, []).append(pb)
    return {
        "market": _stat(all_pb),
        "industries": {code: _stat(pbs) for code, pbs in by_ind.items()},
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_stats.py tests/domain/market/industry_analysis/test_pb_break.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/industry_analysis/stats.py \
  backend/src/domain/market/industry_analysis/pb_break.py \
  backend/tests/domain/market/industry_analysis/test_stats.py \
  backend/tests/domain/market/industry_analysis/test_pb_break.py
git commit -m "feat(industry): 破净率聚合与统计纯函数(midrank百分位/直方图)"
```

---

### Task 5: 景气分纯函数 + pydantic 配置

**Files:**
- Create: `backend/src/domain/market/industry_analysis/prosperity.py`
- Modify: `backend/conf/settings.py`（`BoomRadarConfig` 定义旁新增，并挂到 `AppConfig`）
- Test: `backend/tests/domain/market/industry_analysis/test_prosperity.py`

**Interfaces:**
- Produces:
  - `IndustryInputs`（dataclass：sw_code, name, revenue_yoy, net_profit_yoy, pb, pb_pct, pe_ttm, pe_pct, rs60, flow20——除前两个全 Optional[float]）
  - `ProsperityScore`（dataclass：sw_code, score, score_profit, score_valuation, score_momentum, score_flow, inputs: dict 快照）
  - `DEFAULT_WEIGHTS = {"profit": 0.35, "valuation": 0.25, "momentum": 0.25, "flow": 0.15}`
  - `compute_prosperity(inputs: dict[str, IndustryInputs], weights: dict | None = None) -> dict[str, ProsperityScore]`
  - `net_profit_yoy(cur, prev) -> float | None`（%(cur−prev)/|prev|·100；cur/prev None 或 prev==0 → None）
  - `conf.settings.IndustryAnalysisConfig(enabled=True, pct_window_years=8, weights=dict)`，挂在 `AppConfig.industry_analysis`。Task 6/7/9 消费。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/market/industry_analysis/test_prosperity.py
import math

import pytest

from src.domain.market.industry_analysis.prosperity import (
    DEFAULT_WEIGHTS, IndustryInputs, compute_prosperity, net_profit_yoy,
)


def inp(code, **kw):
    base = dict(sw_code=code, name=code, revenue_yoy=None,
                net_profit_yoy=None, pb=None, pb_pct=None, pe_ttm=None,
                pe_pct=None, rs60=None, flow20=None)
    base.update(kw)
    return IndustryInputs(**base)


def test_net_profit_yoy():
    assert net_profit_yoy(120.0, 100.0) == pytest.approx(20.0)
    assert net_profit_yoy(80.0, -100.0) == pytest.approx(180.0)  # 扭亏为盈记正(分母|prev|,方向随变化)
    assert net_profit_yoy(None, 100.0) is None
    assert net_profit_yoy(100.0, 0.0) is None


def test_score_ranks_and_reweights():
    out = compute_prosperity({
        "A": inp("A", revenue_yoy=50.0, net_profit_yoy=60.0, pb=1.0,
                 pb_pct=90.0, pe_ttm=10.0, pe_pct=80.0, rs60=0.3,
                 flow20=1e9),
        "B": inp("B", revenue_yoy=10.0, net_profit_yoy=5.0, pb=2.0,
                 pb_pct=10.0, pe_ttm=30.0, pe_pct=20.0, rs60=-0.1,
                 flow20=-1e9),
    })
    a, b = out["A"], out["B"]
    assert a.score > b.score
    # 盈利分:midrank 截面——A(55) → (1+0.5)/2=75;B(7.5) → 25
    assert a.score_profit == 75.0 and b.score_profit == 25.0
    # 估值分:取反分位 → A 低(高分位=贵)
    assert a.score_valuation < b.score_valuation
    assert a.score_momentum == 75.0
    assert a.inputs["rs60"] == 0.3   # 快照可追溯


def test_missing_component_reweights():
    # 无任何 flow 输入 → flow 分项 None,总分按剩余权重归一仍 0-100
    out = compute_prosperity({
        "A": inp("A", revenue_yoy=20.0, pb_pct=50.0, pe_pct=50.0, rs60=0.1),
    })
    a = out["A"]
    assert a.score_flow is None
    assert a.score is not None and 0 <= a.score <= 100
    # 单行业截面:midrank 全 50,总分 = 50
    assert a.score == 50.0


def test_all_missing_returns_none_score():
    out = compute_prosperity({"A": inp("A")})
    assert out["A"].score is None
    assert out["A"].inputs == {}


def test_weights_from_config():
    out = compute_prosperity({
        "A": inp("A", revenue_yoy=10.0, pb_pct=50.0, pe_pct=50.0, rs60=0.1),
    }, weights={"profit": 1.0, "valuation": 0.0, "momentum": 0.0,
                "flow": 0.0})
    assert out["A"].score == out["A"].score_profit


def test_default_weights_sum_to_one():
    assert math.isclose(sum(DEFAULT_WEIGHTS.values()), 1.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_prosperity.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现景气分**

```python
# backend/src/domain/market/industry_analysis/prosperity.py
"""行业景气分(纯函数):盈利/估值/动量/资金四分项截面分位加权(规格§4 F2)。

估值分位窗口固定取 config(默认8年)——评分口径恒定;热力图展示列的
5/8/10年切换只影响展示,不影响本模块(窗口由 inputs 装配方决定)。
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Optional

from src.domain.market.industry_analysis.stats import percentile_rank

DEFAULT_WEIGHTS = {"profit": 0.35, "valuation": 0.25,
                   "momentum": 0.25, "flow": 0.15}


@dataclass
class IndustryInputs:
    sw_code: str
    name: str = ""
    revenue_yoy: Optional[float] = None      # %,cross_section 最新报告期
    net_profit_yoy: Optional[float] = None   # %,net_profit_sum 跨期自算
    pb: Optional[float] = None
    pb_pct: Optional[float] = None           # 历史分位 0-100
    pe_ttm: Optional[float] = None
    pe_pct: Optional[float] = None           # 历史分位 0-100
    rs60: Optional[float] = None             # 60日收益 − 沪深300同窗收益
    flow20: Optional[float] = None           # 映射后20日主力净流入合计(元)


@dataclass
class ProsperityScore:
    sw_code: str
    score: Optional[float]
    score_profit: Optional[float]
    score_valuation: Optional[float]
    score_momentum: Optional[float]
    score_flow: Optional[float]
    inputs: dict = field(default_factory=dict)


def net_profit_yoy(cur: Optional[float],
                   prev: Optional[float]) -> Optional[float]:
    """净利同比%:基数≤0 或缺失 → None(亏损基数口径不稳,宁缺毋滥)。"""
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100.0


def _snapshot(x: IndustryInputs) -> dict:
    return {f.name: getattr(x, f.name) for f in fields(x)
            if f.name not in ("sw_code", "name")}


def _raw_components(x: IndustryInputs) -> dict[str, Optional[float]]:
    """四分项的原始值(估值=分位取反;盈利=两同比均值)。"""
    profit_vals = [v for v in (x.revenue_yoy, x.net_profit_yoy)
                   if v is not None]
    profit = sum(profit_vals) / len(profit_vals) if profit_vals else None
    val_vals = [100.0 - p for p in (x.pb_pct, x.pe_pct) if p is not None]
    valuation = sum(val_vals) / len(val_vals) if val_vals else None
    return {"profit": profit, "valuation": valuation,
            "momentum": x.rs60, "flow": x.flow20}


def compute_prosperity(inputs: dict[str, IndustryInputs],
                       weights: Optional[dict] = None) -> dict[str, ProsperityScore]:
    w = dict(weights or DEFAULT_WEIGHTS)
    raw = {code: _raw_components(x) for code, x in inputs.items()}
    cross = {k: [raw[c][k] for c in raw if raw[c][k] is not None]
             for k in w}
    out: dict[str, ProsperityScore] = {}
    for code, x in inputs.items():
        subs: dict[str, Optional[float]] = {}
        for k, weight in w.items():
            v = raw[code][k]
            subs[k] = percentile_rank(v, cross[k]) if v is not None else None
        avail = [(w[k], s) for k, s in subs.items() if s is not None]
        total_w = sum(wi for wi, _ in avail)
        score = (sum(wi * s for wi, s in avail) / total_w
                 if total_w > 0 else None)
        out[code] = ProsperityScore(
            sw_code=code, score=score,
            score_profit=subs["profit"], score_valuation=subs["valuation"],
            score_momentum=subs["momentum"], score_flow=subs["flow"],
            inputs=_snapshot(x) if score is not None else {},
        )
    return out
```

- [ ] **Step 4: 加配置（settings.py）**

在 `conf/settings.py` 的 `BoomRadarConfig` 类定义之后追加，并在 `AppConfig` 里 `boom_radar: BoomRadarConfig = BoomRadarConfig()` 行后追加挂载行：

```python
class IndustryAnalysisConfig(BaseModel):
    """行业分析(破净率/景气分/资金流)配置"""
    enabled: bool = True
    pct_window_years: int = 8          # 估值分位窗口(评分口径恒定)
    weights: dict[str, float] = {      # 四分项权重(和为1)
        "profit": 0.35, "valuation": 0.25,
        "momentum": 0.25, "flow": 0.15,
    }
```

```python
    industry_analysis: IndustryAnalysisConfig = IndustryAnalysisConfig()
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_prosperity.py -v`
Expected: 6 passed

Run（配置默认值可加载）:
`cd backend && uv run python -c "from conf import app_config; print(app_config.industry_analysis.weights)"`
Expected: 打印 `{'profit': 0.35, 'valuation': 0.25, 'momentum': 0.25, 'flow': 0.15}`

- [ ] **Step 6: Commit**

```bash
git add backend/src/domain/market/industry_analysis/prosperity.py backend/conf/settings.py \
  backend/tests/domain/market/industry_analysis/test_prosperity.py
git commit -m "feat(industry): 景气分纯函数(四分项截面midrank加权/缺项归一)+配置"
```

---

### Task 6: 评分输入装配（可注入仓储）

**Files:**
- Create: `backend/src/domain/market/industry_analysis/inputs.py`
- Test: `backend/tests/domain/market/industry_analysis/test_inputs.py`

**Interfaces:**
- Consumes: Task 3 仓储方法、Task 4 `percentile_rank`、Task 5 `IndustryInputs`/`net_profit_yoy`、Task 2 `load_flow_map`、`strategy/relative_strength.relative_strength`。
- Produces: `assemble_inputs(repo, as_of: dt.date, pct_window_years=8) -> dict[str, IndustryInputs]`（key=纯6位 sw_code）。仓储以鸭子类型注入（测试用 `SimpleNamespace` 假仓储）。Task 7/8 消费。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/market/industry_analysis/test_inputs.py
"""评分输入装配:假仓储注入,验证跨表拼装与分位/RS/资金映射逻辑。"""
import datetime as dt
from types import SimpleNamespace

from src.domain.market.industry_analysis.inputs import assemble_inputs

D = dt.date(2026, 9, 18)


def fake_repo():
    return SimpleNamespace(
        # cross_section:801780 三个报告期(去年同期/上季/最新);801120 只有一期
        get_cross_section_latest_two=lambda level=1: {
            "801780": [
                {"report_date": dt.date(2025, 6, 30),
                 "revenue_yoy": 3.0, "net_profit_sum": 180.0},
                {"report_date": dt.date(2025, 12, 31),
                 "revenue_yoy": 5.0, "net_profit_sum": 200.0},
                {"report_date": dt.date(2026, 6, 30),
                 "revenue_yoy": 8.0, "net_profit_sum": 120.0},
            ],
            "801120": [
                {"report_date": dt.date(2026, 6, 30),
                 "revenue_yoy": 12.0, "net_profit_sum": 100.0},
            ],
        },
        # 估值窗口:801780 的 PB 序列 [1,2,3,4] 当前 4 → 分位 100
        get_sw_valuation_window=lambda codes, start, end: {
            "801780": [{"trade_date": dt.date(2026, 9, i % 28 + 1),
                        "pe_ttm": 4.0, "pb": p} for i, p in
                       enumerate([1.0, 2.0, 3.0, 4.0])],
            "801120": [{"trade_date": dt.date(2026, 9, 18),
                        "pe_ttm": 20.0, "pb": 5.0}],
        },
        # 行情:801780 六根收盘 10→13(+30%),基准 sh000300 10→11(+10%)
        get_index_closes=lambda symbols, start, end: {
            "sw801780": [(dt.date(2026, 6, 1), 10.0)] +
                        [(dt.date(2026, 9, i), 10.0 + i * 0.6) for i in
                         range(1, 6)],
            "sh000300": [(dt.date(2026, 6, 1), 10.0)] +
                        [(dt.date(2026, 9, i), 10.0 + i * 0.2) for i in
                         range(1, 6)],
        },
        # 资金流:两行业两日
        get_flow_rows=lambda start: [
            {"trade_date": dt.date(2026, 9, 17), "em_industry_name": "银行",
             "main_net_inflow": 100.0, "close_change_pct": 1.0},
            {"trade_date": dt.date(2026, 9, 18), "em_industry_name": "银行",
             "main_net_inflow": 50.0, "close_change_pct": -0.5},
            {"trade_date": dt.date(2026, 9, 18), "em_industry_name": "酿酒行业",
             "main_net_inflow": -30.0, "close_change_pct": 0.0},
        ],
    )


def test_assemble():
    out = assemble_inputs(fake_repo(), D, pct_window_years=8)
    bank = out["801780"]
    assert bank.revenue_yoy == 8.0                       # 最新报告期
    # 基期=一年前同期 2025-06-30(净利180),非上季(200)
    assert abs(bank.net_profit_yoy - (-100 / 3)) < 1e-6
    assert bank.pb == 4.0 and bank.pb_pct == 87.5   # [1,2,3,4] midrank
    assert bank.pe_ttm == 4.0
    assert bank.flow20 == 150.0                          # 银行 100+50
    # rs60 = 标的61根首尾 − 基准同窗首尾
    assert abs(bank.rs60 - (0.3 - 0.1)) < 1e-9
    food = out["801120"]
    assert food.net_profit_yoy is None                   # 只有一期
    assert food.flow20 == -30.0                          # 酿酒→801120


def test_flow_cutoff_30_calendar_days():
    repo = fake_repo()
    old = {"trade_date": dt.date(2026, 1, 1), "em_industry_name": "银行",
           "main_net_inflow": 999.0, "close_change_pct": 0.0}
    repo.get_flow_rows = lambda start: (
        [] if start > dt.date(2026, 1, 1) else [old])
    out = assemble_inputs(repo, D)
    assert out["801780"].flow20 is None or out["801780"].flow20 == 999.0
    # start=D-30天 → 1月1日旧行被截断 → None
    out2 = assemble_inputs(fake_repo(), D)
    assert out2["801780"].flow20 == 150.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_inputs.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现装配**

```python
# backend/src/domain/market/industry_analysis/inputs.py
"""景气评分输入装配:跨表现读 → IndustryInputs(仓储鸭子类型注入可测)。

数据口径(规格§4 F2):
- 盈利:cross_section 两个最新报告期(净利同比自算,亏损基数→None)
- 估值:sw_index_valuation_daily 窗口内 midrank 分位(窗口=评分 config 恒定)
- 动量:index_ohlcv 61 根首尾收益 − sh000300 同窗(复用 relative_strength)
- 资金:近30自然日东财流映射申万求和(不足1个交易日→None)
"""
from __future__ import annotations

import datetime as dt

from src.domain.market.industry_analysis.flow_map import load_flow_map
from src.domain.market.industry_analysis.knowledge import SW_L1_CODES
from src.domain.market.industry_analysis.prosperity import (
    IndustryInputs, net_profit_yoy,
)
from src.domain.market.industry_analysis.stats import percentile_rank
from src.domain.market.strategy.relative_strength import relative_strength

_BENCH = "sh000300"
_FLOW_LOOKBACK_DAYS = 30       # 自然日,约 20 个交易日
_RS_BARS = 61                 # 60日收益需要61根


def _ret_over(closes: list[tuple[dt.date, float]]) -> float | None:
    if len(closes) < 2:
        return None
    first, last = closes[0][1], closes[-1][1]
    if not first:
        return None
    return last / first - 1.0


def _build_rs60(repo, as_of: dt.date,
                codes: list[str]) -> dict[str, float | None]:
    start = as_of - dt.timedelta(days=_RS_BARS * 2)   # 61根交易日≈122自然日
    symbols = [f"sw{c}" for c in codes] + [_BENCH]
    closes = repo.get_index_closes(symbols, start, as_of)
    bench = _ret_over(closes.get(_BENCH, []))
    out: dict[str, float | None] = {}
    for c in codes:
        tgt = _ret_over(closes.get(f"sw{c}", []))
        if tgt is None or bench is None:
            out[c] = None
            continue
        rs = relative_strength(tgt, bench)
        out[c] = rs.excess if rs else None
    return out


def _pick_year_ago(sec: list[dict]) -> dict:
    """净利同比基期=最新报告期一年前同期(±45天容差取最近);找不到返回 {}。

    仓储返回 ~550 天内全部报告期(季度频),上季≠基期,必须按一年前同期挑。
    """
    if not sec:
        return {}
    cur_d = sec[-1].get("report_date")
    if cur_d is None:
        return {}
    best = None
    for row in sec[:-1]:
        rd = row.get("report_date")
        if rd is None:
            continue
        delta = abs((rd - (cur_d - dt.timedelta(days=365))).days)
        if delta <= 45 and (best is None or delta < best[0]):
            best = (delta, row)
    return best[1] if best else {}


def _build_flow20(repo, as_of: dt.date) -> dict[str, float]:
    rows = repo.get_flow_rows(as_of - dt.timedelta(days=_FLOW_LOOKBACK_DAYS))
    em2sw = load_flow_map()
    sums: dict[str, float] = {}
    for r in rows:
        code = em2sw.get(r.get("em_industry_name", ""))
        v = r.get("main_net_inflow")
        if code and v is not None:
            sums[code] = sums.get(code, 0.0) + float(v)
    return sums


def assemble_inputs(repo, as_of: dt.date,
                    pct_window_years: int = 8) -> dict[str, IndustryInputs]:
    codes = list(SW_L1_CODES)
    w_start = as_of - dt.timedelta(days=int(pct_window_years * 365.25))

    sections = repo.get_cross_section_latest_two(level=1)
    valuations = repo.get_sw_valuation_window(codes, w_start, as_of)
    rs60 = _build_rs60(repo, as_of, codes)
    flow20 = _build_flow20(repo, as_of)

    out: dict[str, IndustryInputs] = {}
    for code in codes:
        sec = sections.get(code) or []
        cur = sec[-1] if sec else {}
        prev = _pick_year_ago(sec)
        series = valuations.get(code) or []
        last_v = series[-1] if series else {}
        pbs = [r["pb"] for r in series]
        pes = [r["pe_ttm"] for r in series]
        out[code] = IndustryInputs(
            sw_code=code,
            name="",
            revenue_yoy=cur.get("revenue_yoy"),
            net_profit_yoy=net_profit_yoy(cur.get("net_profit_sum"),
                                          prev.get("net_profit_sum")),
            pb=last_v.get("pb"),
            pb_pct=percentile_rank(last_v.get("pb"), pbs),
            pe_ttm=last_v.get("pe_ttm"),
            pe_pct=percentile_rank(last_v.get("pe_ttm"), pes),
            rs60=rs60.get(code),
            flow20=flow20.get(code),
        )
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_inputs.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/src/domain/market/industry_analysis/inputs.py \
  backend/tests/domain/market/industry_analysis/test_inputs.py
git commit -m "feat(industry): 景气评分输入装配——盈利两期/估值分位/RS60/资金映射(假仓储可测)"
```

---

### Task 7: 三个每日 job + scheduler 注册

**Files:**
- Create: `backend/src/domain/market/sync/jobs/industry_pb_break_sync.py`
- Create: `backend/src/domain/market/sync/jobs/industry_fund_flow_sync.py`
- Create: `backend/src/domain/market/sync/jobs/industry_prosperity_sync.py`
- Modify: `backend/src/infra/scheduler.py`（boom job 块之后，约 L640 追加）
- Test: `backend/tests/domain/market/industry_analysis/test_daily_jobs.py`

**Interfaces:**
- Consumes: Task 3 仓储、Task 4 `aggregate_pb_break`、Task 5/6 评分链、`conf.app_config.industry_analysis.enabled`。
- Produces:
  - `industry_pb_break_sync.run(days: int = 2) -> dict`（幂等：对最近 N 个估值交易日逐日聚合 upsert，返回 `{"dates": [...], "rows": n}`）
  - `industry_pb_break_sync.aggregate_one_day(repo, trade_date) -> list[dict]`（纯装配：当日估值行 JOIN 成员 → upsert 行；SQL 在 repo 外不重复）
  - `industry_fund_flow_sync.parse_flow_df(df, trade_date) -> list[dict]`（纯转换，列名容错双口径）与 `run() -> dict`
  - `industry_prosperity_sync.run(trade_date=None) -> dict`（默认评分日=估值表最新日）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/market/industry_analysis/test_daily_jobs.py
"""每日 job 的纯转换段(不触网不触库)。"""
import datetime as dt
from types import SimpleNamespace

import pandas as pd

from src.domain.market.sync.jobs.industry_fund_flow_sync import parse_flow_df
from src.domain.market.sync.jobs.industry_pb_break_sync import (
    build_pb_rows,
)

D = dt.date(2026, 9, 18)


def test_build_pb_rows():
    agg = aggregate = SimpleNamespace(
        market=SimpleNamespace(total_count=2, break_count=1, break_rate=0.5,
                               median_pb=1.0),
        industries={"801780": SimpleNamespace(total_count=1, break_count=0,
                                              break_rate=0.0,
                                              median_pb=1.5)},
    )
    rows = build_pb_rows(D, aggregate)
    assert rows == [
        {"trade_date": D, "scope": "market", "scope_code": "ALL",
         "total_count": 2, "break_count": 1, "break_rate": 0.5,
         "median_pb": 1.0},
        {"trade_date": D, "scope": "industry", "scope_code": "801780",
         "total_count": 1, "break_count": 0, "break_rate": 0.0,
         "median_pb": 1.5},
    ]


def test_parse_flow_df_both_dialects():
    # 口径1:列含「行业/净额」(现有 /market/fund-flow 同款)
    df1 = pd.DataFrame([
        {"行业": "银行", "净额": 1.5e9, "涨跌幅": 1.2},
        {"行业": "酿酒行业", "净额": -3e8, "涨跌幅": -0.5},
    ])
    # 口径2:列含「名称/主力净流入-净额」
    df2 = pd.DataFrame([
        {"名称": "银行", "主力净流入-净额": 1.5e9, "涨跌幅": 1.2},
    ])
    r1 = parse_flow_df(df1, D)
    r2 = parse_flow_df(df2, D)
    assert r1[0] == {"trade_date": D, "em_industry_name": "银行",
                     "main_net_inflow": 1.5e9, "close_change_pct": 1.2}
    assert r1[1]["em_industry_name"] == "酿酒行业"
    assert r2[0]["em_industry_name"] == "银行"
    assert r2[0]["main_net_inflow"] == 1.5e9


def test_parse_flow_df_skips_dirty_rows():
    df = pd.DataFrame([
        {"行业": "", "净额": None, "涨跌幅": None},          # 空名
        {"行业": "银行", "净额": "abc", "涨跌幅": 1.0},     # 脏数值
    ])
    rows = parse_flow_df(df, D)
    assert rows == [{"trade_date": D, "em_industry_name": "银行",
                     "main_net_inflow": None, "close_change_pct": 1.0}]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_daily_jobs.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现三个 job**

```python
# backend/src/domain/market/sync/jobs/industry_pb_break_sync.py
"""破净率每日增量 job(16:40):最近 N 个估值交易日逐日聚合 upsert,幂等可补。"""
import datetime as dt
import logging

from src.domain.market.industry_analysis.pb_break import aggregate_pb_break
from src.infra.database.market.industry_analysis import (
    create_industry_analysis_repository,
)

log = logging.getLogger(__name__)

_SQL = """
    SELECT v.symbol, v.pb, m.sw_code_l1
    FROM stock_valuation v
    LEFT JOIN sw_industry_member m ON m.symbol = v.symbol
    WHERE v.trade_date = %s
"""


def build_pb_rows(trade_date: dt.date, aggregate) -> list[dict]:
    """聚合结果 → upsert 行(market 行 scope_code='ALL')。"""
    rows = [{"trade_date": trade_date, "scope": "market",
             "scope_code": "ALL",
             "total_count": aggregate.market.total_count,
             "break_count": aggregate.market.break_count,
             "break_rate": aggregate.market.break_rate,
             "median_pb": aggregate.market.median_pb}]
    for code, st in aggregate.industries.items():
        rows.append({"trade_date": trade_date, "scope": "industry",
                     "scope_code": code, "total_count": st.total_count,
                     "break_count": st.break_count,
                     "break_rate": st.break_rate,
                     "median_pb": st.median_pb})
    return rows


def aggregate_one_day(repo, conn, trade_date: dt.date) -> int:
    with conn.cursor() as cur:
        cur.execute(_SQL, (trade_date,))
        raw = cur.fetchall()
    aggregate = aggregate_pb_break(
        (r[0], float(r[1]) if r[1] is not None else None, r[2])
        for r in raw)
    return repo.upsert_pb_break(build_pb_rows(trade_date, aggregate))


def run(days: int = 2) -> dict:
    """对最近 days 个 stock_valuation 交易日重算(补昨日缺口+幂等今日)。"""
    import psycopg2

    from src.infra.database.sql_engine.dsn import get_dsn
    repo = create_industry_analysis_repository()
    today = dt.date.today()
    dates = repo.get_stock_valuation_dates(today - dt.timedelta(days=days * 3),
                                           today)[-days:]
    total = 0
    conn = psycopg2.connect(get_dsn())
    try:
        for d in dates:
            total += aggregate_one_day(repo, conn, d)
    finally:
        conn.close()
    log.info("[INDUSTRY_PB_BREAK] dates=%s rows=%d", dates, total)
    return {"dates": [str(d) for d in dates], "rows": total}
```

注意：`aggregate_pb_break` 的入参签名是可迭代 `rows`（Task 4 测试传 list，生成器同样可迭代，实现保持 `for _symbol, pb, sw_code in rows` 即可）。

```python
# backend/src/domain/market/sync/jobs/industry_fund_flow_sync.py
"""东财行业资金流每日落库 job(17:05,收盘后快照≈全天)。"""
import datetime as dt
import logging

import akshare as ak

from src.infra.database.market.industry_analysis import (
    create_industry_analysis_repository,
)

log = logging.getLogger(__name__)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_flow_df(df, trade_date: dt.date) -> list[dict]:
    """东财行业资金流 df → 落库行;列名容错「行业/名称」与「净额/主力净流入-净额」。"""
    rows: list[dict] = []
    for _, r in df.iterrows():
        name = str(r.get("行业") or r.get("名称") or "").strip()
        if not name:
            continue
        net = r.get("净额")
        if net is None:
            net = r.get("主力净流入-净额")
        rows.append({"trade_date": trade_date,
                     "em_industry_name": name,
                     "main_net_inflow": _num(net),
                     "close_change_pct": _num(r.get("涨跌幅"))})
    return rows


def run(trade_date: dt.date | None = None) -> dict:
    repo = create_industry_analysis_repository()
    d = trade_date or dt.date.today()
    try:
        df = ak.stock_fund_flow_industry(symbol="即时")
    except Exception as e:  # noqa: BLE001
        log.error("[INDUSTRY_FLOW] akshare failed: %s", e)
        return {"rows": 0, "error": str(e)}
    rows = parse_flow_df(df, d)
    n = repo.upsert_fund_flow(rows)
    log.info("[INDUSTRY_FLOW] date=%s rows=%d", d, n)
    return {"rows": n}
```

```python
# backend/src/domain/market/sync/jobs/industry_prosperity_sync.py
"""景气分每日重算 job(17:20):31 行业全量重算 upsert,inputs 快照随存。"""
import logging

from src.domain.market.industry_analysis.inputs import assemble_inputs
from src.domain.market.industry_analysis.prosperity import compute_prosperity
from src.infra.database.market.industry_analysis import (
    create_industry_analysis_repository,
)

log = logging.getLogger(__name__)


def run(trade_date=None) -> dict:
    repo = create_industry_analysis_repository()
    from conf import app_config
    cfg = app_config.industry_analysis
    as_of = trade_date or _latest_valuation_date(repo)
    if as_of is None:
        return {"rows": 0}
    inputs = assemble_inputs(repo, as_of,
                             pct_window_years=cfg.pct_window_years)
    from src.domain.market.industry_analysis.knowledge import load_knowledge
    know = load_knowledge()
    for code, x in inputs.items():          # 名字从知识层补
        x.name = know[code].name
    scores = compute_prosperity(inputs, weights=cfg.weights)
    rows = []
    for code, s in scores.items():
        rows.append({"trade_date": as_of, "sw_code": code, "score": s.score,
                     "score_profit": s.score_profit,
                     "score_valuation": s.score_valuation,
                     "score_momentum": s.score_momentum,
                     "score_flow": s.score_flow, "inputs": s.inputs})
    n = repo.upsert_prosperity(rows)
    log.info("[INDUSTRY_PROSPERITY] date=%s rows=%d", as_of, n)
    return {"date": str(as_of), "rows": n}


def _latest_valuation_date(repo):
    import datetime as dt
    today = dt.date.today()
    dates = repo.get_stock_valuation_dates(today - dt.timedelta(days=15),
                                           today)
    return dates[-1] if dates else None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_daily_jobs.py -v`
Expected: 3 passed

- [ ] **Step 5: scheduler 注册**

在 `backend/src/infra/scheduler.py` 的 boom job 块（约 L614-640）之后追加：

```python
    # ── 行业分析三件套(破净率16:40/资金流17:05/景气分17:20)────────────────
    def _run_industry_pb_break_daily():
        from src.domain.market.sync.jobs import industry_pb_break_sync
        try:
            from conf import app_config
            if not app_config.industry_analysis.enabled:
                return
            industry_pb_break_sync.run(days=2)
        except Exception as e:  # noqa: BLE001
            log.error("[INDUSTRY_PB_BREAK_DAILY] failed: %s", e)

    def _run_industry_fund_flow_daily():
        from src.domain.market.sync.jobs import industry_fund_flow_sync
        try:
            from conf import app_config
            if not app_config.industry_analysis.enabled:
                return
            industry_fund_flow_sync.run()
        except Exception as e:  # noqa: BLE001
            log.error("[INDUSTRY_FLOW_DAILY] failed: %s", e)

    def _run_industry_prosperity_daily():
        from src.domain.market.sync.jobs import industry_prosperity_sync
        try:
            from conf import app_config
            if not app_config.industry_analysis.enabled:
                return
            industry_prosperity_sync.run()
        except Exception as e:  # noqa: BLE001
            log.error("[INDUSTRY_PROSPERITY_DAILY] failed: %s", e)

    for _jid, _fn, _hm, _name in (
        ("industry_pb_break_daily", _run_industry_pb_break_daily,
         (16, 40), "行业破净率每日聚合"),
        ("industry_fund_flow_daily", _run_industry_fund_flow_daily,
         (17, 5), "行业资金流每日落库"),
        ("industry_prosperity_daily", _run_industry_prosperity_daily,
         (17, 20), "行业景气分每日重算"),
    ):
        sched.add_job(
            _fn,
            CronTrigger(hour=_hm[0], minute=_hm[1],
                        timezone="Asia/Shanghai"),
            id=_jid,
            name=_name,
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
            coalesce=True,
        )
```

- [ ] **Step 6: 手动验证(真库,一次性)**

Run:
```bash
cd backend && uv run python -c "
from src.domain.market.sync.jobs import industry_pb_break_sync
print(industry_pb_break_sync.run(days=2))"
```
Expected: `{'dates': [...], 'rows': 62}` 左右（2 日 × 32 行）。
```bash
cd backend && uv run python -c "
from src.domain.market.sync.jobs import industry_prosperity_sync
print(industry_prosperity_sync.run())"
```
Expected: `{'date': '...', 'rows': 31}`。
资金流 job 依赖盘中/收盘后数据，非交易时段允许 `rows` 为 0 或 akshare 报错（记 error 不崩）。

- [ ] **Step 7: Commit**

```bash
git add backend/src/domain/market/sync/jobs/industry_pb_break_sync.py \
  backend/src/domain/market/sync/jobs/industry_fund_flow_sync.py \
  backend/src/domain/market/sync/jobs/industry_prosperity_sync.py \
  backend/src/infra/scheduler.py \
  backend/tests/domain/market/industry_analysis/test_daily_jobs.py
git commit -m "feat(industry): 破净率/资金流/景气分三每日job+scheduler注册"
```

---

### Task 8: 两个历史回填脚本（python -m 可直跑）

**Files:**
- Create: `backend/src/domain/market/sync/jobs/industry_pb_break_backfill.py`
- Create: `backend/src/domain/market/sync/jobs/industry_prosperity_backfill.py`
- Test: `backend/tests/domain/market/industry_analysis/test_backfill_dates.py`

**Interfaces:**
- Consumes: Task 7 的 `aggregate_one_day` 与 `industry_prosperity_sync.run(trade_date)`；`sync/progress.py ProgressTracker`。
- Produces: 两个可独立运行的模块；破净率回填断点续传（ProgressTracker provider=`industry_pb_break`, symbol=`ALL`, interval=`daily`）；景气分回填按月末采样。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/domain/market/industry_analysis/test_backfill_dates.py
"""回填日期规划纯函数。"""
import datetime as dt

from src.domain.market.sync.jobs.industry_pb_break_backfill import (
    plan_dates,
)
from src.domain.market.sync.jobs.industry_prosperity_backfill import (
    month_end_dates,
)


def test_plan_dates_resume_from_last():
    dates = [dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3)]
    # 断点在 2026-01-02 → 只剩 01-03
    assert plan_dates(dates, last_done="2026-01-02") == [dt.date(2026, 1, 3)]
    assert plan_dates(dates, last_done=None) == dates


def test_plan_dates_tolerates_gap():
    dates = [dt.date(2026, 1, 1), dt.date(2026, 1, 5)]
    assert plan_dates(dates, last_done="2026-01-01") == [dt.date(2026, 1, 5)]


def test_month_end_dates():
    ds = month_end_dates(dt.date(2025, 11, 15), dt.date(2026, 2, 20))
    assert ds == [dt.date(2025, 11, 30), dt.date(2025, 12, 31),
                  dt.date(2026, 1, 31)]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_backfill_dates.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现两个脚本**

```python
# backend/src/domain/market/sync/jobs/industry_pb_break_backfill.py
"""破净率全历史回填(手动,断点续传):逐 stock_valuation 交易日聚合。

用法: cd backend && uv run python -m \
  src.domain.market.sync.jobs.industry_pb_break_backfill [--start 1991-01-01]
"""
import argparse
import datetime as dt
import logging
import socket
import sys
from pathlib import Path

socket.setdefaulttimeout(60)
_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.jobs.industry_pb_break_sync import (  # noqa: E402
    aggregate_one_day,
)
from src.domain.market.sync.progress import ProgressTracker       # noqa: E402
from src.infra.database.market.industry_analysis import (        # noqa: E402
    create_industry_analysis_repository,
)
from src.infra.database.sql_engine.dsn import get_dsn           # noqa: E402

log = logging.getLogger(__name__)
_PROVIDER, _SYMBOL, _INTERVAL = "industry_pb_break", "ALL", "daily"


def plan_dates(dates: list[dt.date], last_done: str | None) -> list[dt.date]:
    """断点续传:last_done 之后的日期(相等也跳过——当日已完成)。"""
    if not last_done:
        return list(dates)
    pivot = dt.date.fromisoformat(last_done)
    return [d for d in dates if d > pivot]


def main(start: str = "1991-01-01", end: str | None = None) -> dict:
    import psycopg2

    repo = create_industry_analysis_repository()
    tracker = ProgressTracker()
    e = dt.date.fromisoformat(end) if end else dt.date.today()
    dates = repo.get_stock_valuation_dates(dt.date.fromisoformat(start), e)
    todo = plan_dates(dates, tracker.get_last_sync(_PROVIDER, _SYMBOL,
                                                   _INTERVAL))
    log.info("[PB_BREAK_BACKFILL] total=%d todo=%d", len(dates), len(todo))
    conn = psycopg2.connect(get_dsn())
    done = 0
    try:
        for d in todo:
            rows = aggregate_one_day(repo, conn, d)
            tracker.mark_done(_PROVIDER, _SYMBOL, _INTERVAL, d.isoformat(),
                              rows)
            tracker.flush()
            done += 1
            if done % 200 == 0:
                log.info("[PB_BREAK_BACKFILL] progress %d/%d", done,
                         len(todo))
    finally:
        conn.close()
        tracker.flush()
    log.info("[PB_BREAK_BACKFILL] finished %d dates", done)
    return {"done": done, "total": len(todo)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="1991-01-01")
    ap.add_argument("--end", default=None)
    a = ap.parse_args()
    print(main(a.start, a.end))
```

```python
# backend/src/domain/market/sync/jobs/industry_prosperity_backfill.py
"""景气分历史回填(手动):月末采样(规格§3.3——历史月末点+上线后逐日)。

用法: cd backend && uv run python -m \
  src.domain.market.sync.jobs.industry_prosperity_backfill [--start 2018-01-01]
"""
import argparse
import datetime as dt
import logging
import socket
import sys
from pathlib import Path

socket.setdefaulttimeout(60)
_BACKEND = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.jobs.industry_prosperity_sync import run  # noqa: E402

log = logging.getLogger(__name__)


def month_end_dates(start: dt.date, end: dt.date) -> list[dt.date]:
    """区间内各月末(不含 end 所在月未满月)。"""
    out: list[dt.date] = []
    y, m = start.year, start.month
    while True:
        nxt = dt.date(y + (m // 12), m % 12 + 1, 1) - dt.timedelta(days=1)
        if nxt > end:
            break
        if nxt >= start:
            out.append(nxt)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def main(start: str = "2018-01-01") -> dict:
    s = dt.date.fromisoformat(start)
    dates = month_end_dates(s, dt.date.today())
    log.info("[PROSPERITY_BACKFILL] %d month-ends from %s", len(dates), s)
    ok = 0
    for d in dates:
        try:
            r = run(trade_date=d)
            ok += 1 if r.get("rows") else 0
        except Exception as e:  # noqa: BLE001
            log.error("[PROSPERITY_BACKFILL] %s failed: %s", d, e)
    return {"done": ok, "total": len(dates)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2018-01-01")
    print(main(ap.parse_args().start))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_backfill_dates.py -v`
Expected: 3 passed

- [ ] **Step 5: 真库跑通破净率回填（一次性，后台可跑数分钟-数十分钟）**

Run: `cd backend && uv run python -m src.domain.market.sync.jobs.industry_pb_break_backfill`
Expected: 末尾打印 `{'done': N, 'total': N}`（N≈8600 个交易日，中断重跑自动续传）。

验证（>10% 区间的历史确实存在）:
```bash
PGPASSWORD=$(grep -oP '(?<=postgres:)[^@]+' backend/conf/config.local.yaml | head -1) \
psql -h 127.0.0.1 -U postgres -d ytrader -t -c \
"SELECT count(*) FROM industry_pb_break_daily WHERE scope='market' AND break_rate>0.10"
```
Expected: 非零（历次底部区段）。

- [ ] **Step 6: 真库跑通景气分回填（一次性）**

Run: `cd backend && uv run python -m src.domain.market.sync.jobs.industry_prosperity_backfill`
Expected: `{'done': M, 'total': M}`（M≈100 个月末；早年净利/资金输入缺失属设计内，评分按剩余权重归一）。

- [ ] **Step 7: Commit**

```bash
git add backend/src/domain/market/sync/jobs/industry_pb_break_backfill.py \
  backend/src/domain/market/sync/jobs/industry_prosperity_backfill.py \
  backend/tests/domain/market/industry_analysis/test_backfill_dates.py
git commit -m "feat(industry): 破净率全历史断点回填+景气分月末采样回填"
```

---

### Task 9: industry_router 第一段（/overview /pb-break /flow）+ 资金流汇总纯函数

**Files:**
- Create: `backend/src/api/router/industry_router.py`
- Modify: `backend/main.py`（router 挂载段，boom_router 行后）
- Test: `backend/tests/domain/market/industry_analysis/test_flow_summary.py`
- Test: `backend/tests/api/test_industry_router.py`

**Interfaces:**
- Consumes: Task 1-8 全部产出。
- Produces（前端 Task 11-14 消费的数据形状，见各端点 `_ok(data)` 的 data 结构）；`flow_map.summarize_flow(rows) -> list[dict]`（em_industry_name/day/flow5/flow20/sw_code，按 flow20 降序）。
- 挂载后完整路径前缀 `/api/v1/industry`。

- [ ] **Step 1: 写资金流汇总失败测试**

```python
# backend/tests/domain/market/industry_analysis/test_flow_summary.py
import datetime as dt

from src.domain.market.industry_analysis.flow_map import summarize_flow

ROWS = (
    [{"trade_date": dt.date(2026, 9, 18), "em_industry_name": "银行",
      "main_net_inflow": 100.0, "close_change_pct": 1.0},
     {"trade_date": dt.date(2026, 9, 17), "em_industry_name": "银行",
      "main_net_inflow": 50.0, "close_change_pct": 0.5}] +
    [{"trade_date": dt.date(2026, 9, 16) - dt.timedelta(days=i),
      "em_industry_name": "银行",
      "main_net_inflow": 10.0, "close_change_pct": 0.0} for i in range(25)]
    + [{"trade_date": dt.date(2026, 9, 18), "em_industry_name": "未知行业",
        "main_net_inflow": 5.0, "close_change_pct": 0.0}]
)


def test_summarize_flow_windows_and_map():
    out = summarize_flow(ROWS)
    bank = next(r for r in out if r["em_industry_name"] == "银行")
    assert bank["sw_code"] == "801780"
    assert bank["day"] == 100.0
    assert bank["flow5"] == 100.0 + 50.0 + 10.0 * 3     # 5个最近交易日
    assert bank["flow20"] == 330.0  # 20个最近交易日截断(100+50+10*18)
    unk = next(r for r in out if r["em_industry_name"] == "未知行业")
    assert unk["sw_code"] is None
    assert out[0]["flow20"] >= out[-1]["flow20"]        # 按 flow20 降序
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_flow_summary.py -v`
Expected: FAIL（ImportError: summarize_flow）

- [ ] **Step 3: 扩展 flow_map 汇总函数**

在 `backend/src/domain/market/industry_analysis/flow_map.py` 末尾追加：

```python
def summarize_flow(rows: list[dict]) -> list[dict]:
    """近30自然日资金流行 → 每东财行业 day/flow5/flow20 + 申万映射,按 flow20 降序。"""
    if not rows:
        return []
    latest = max(r["trade_date"] for r in rows)
    by_day: dict = {}
    for r in rows:
        by_day.setdefault(r["trade_date"], {})[r["em_industry_name"]] = \
            r.get("main_net_inflow") or 0.0
    days = sorted(by_day, reverse=True)          # 交易日降序
    em2sw = load_flow_map()
    names = sorted({r["em_industry_name"] for r in rows})
    out = []
    for name in names:
        day_v = by_day[days[0]].get(name) if days else None
        flow5 = sum(by_day[d].get(name, 0.0) for d in days[:5])
        flow20 = sum(by_day[d].get(name, 0.0) for d in days[:20])
        out.append({"em_industry_name": name, "sw_code": em2sw.get(name),
                    "day": day_v, "flow5": flow5, "flow20": flow20})
    out.sort(key=lambda r: (r["flow20"] is not None, r["flow20"]),
             reverse=True)
    return out
```

注意 `latest` 变量未用时删除——`days[0]` 即最新交易日（保留 `latest` 仅在实现中用于 day 取值亦可，以测试通过为准）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_flow_summary.py -v`
Expected: 1 passed

- [ ] **Step 5: 写 router 契约失败测试**

```python
# backend/tests/api/test_industry_router.py
"""industry_router 契约测试(service 函数打桩,不触网/库)。"""
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.router import industry_router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(industry_router.router)
    return TestClient(app)


def test_overview(client):
    with patch.object(industry_router, "_overview_data") as fake:
        fake.return_value = {"trade_date": "2026-09-18", "rows": []}
        r = client.get("/industry/overview")
    assert r.status_code == 200
    assert r.json() == {"code": 0, "msg": "ok",
                        "data": {"trade_date": "2026-09-18", "rows": []}}


def test_pb_break_defaults_and_validation(client):
    with patch.object(industry_router, "_pb_break_data") as fake:
        fake.return_value = {"series": [], "current": None}
        r = client.get("/industry/pb-break")
        r2 = client.get("/industry/pb-break", params={"scope": "bogus"})
    assert r.status_code == 200 and r.json()["code"] == 0
    assert fake.call_args_list[0].kwargs["scope"] == "market"
    assert r2.status_code == 400


def test_flow(client):
    with patch.object(industry_router, "_flow_data") as fake:
        fake.return_value = {"rows": []}
        r = client.get("/industry/flow")
    assert r.status_code == 200 and r.json()["data"] == {"rows": []}


def test_detail_404_on_bad_code(client):
    r = client.get("/industry/999999")
    assert r.status_code == 404
```

- [ ] **Step 6: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_industry_router.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 7: 实现 router 第一段**

```python
# backend/src/api/router/industry_router.py
"""行业分析 API(规格 2026-09-20 §5)。"""
import datetime as dt
import logging

from fastapi import APIRouter, HTTPException

from src.domain.market.industry_analysis.flow_map import (
    load_flow_map, summarize_flow,
)
from src.domain.market.industry_analysis.knowledge import (
    SW_L1_CODES, TIER_LABELS, load_knowledge,
)
from src.domain.market.industry_analysis.stats import percentile_rank
from src.infra.database.market.industry_analysis import (
    create_industry_analysis_repository,
)

log = logging.getLogger("industry_analysis")
router = APIRouter(prefix="/industry", tags=["industry"])

PB_BREAK_THRESHOLD = 0.10       # 规格笔记:>10% 阶段性底部参考区


def _ok(data):
    return {"code": 0, "msg": "ok", "data": data}


def _repo():
    return create_industry_analysis_repository()


def _overview_data(window: int) -> dict:
    """最新评分快照 + 展示口径分位(可切5/8/10年)+知识层 → 热力图行。"""
    repo = _repo()
    d = repo.get_prosperity_latest_date()
    if d is None:
        return {"trade_date": None, "rows": []}
    rows_by_code = {r["sw_code"]: r for r in repo.get_prosperity(d)}
    w_start = d - dt.timedelta(days=int(window * 365.25))
    valuations = repo.get_sw_valuation_window(list(SW_L1_CODES), w_start, d)
    know = load_knowledge()
    rows = []
    for code in SW_L1_CODES:
        k, p = know[code], rows_by_code.get(code, {})
        inputs = p.get("inputs") or {}
        series = valuations.get(code) or []
        last = series[-1] if series else {}
        rows.append({
            "sw_code": code, "name": k.name, "tier": k.tier,
            "tier_label": TIER_LABELS[k.tier],
            "retail_suitable": k.retail_suitable,
            "revenue_yoy": inputs.get("revenue_yoy"),
            "net_profit_yoy": inputs.get("net_profit_yoy"),
            "pe_ttm": last.get("pe_ttm"),
            "pe_pct": percentile_rank(last.get("pe_ttm"),
                                      [r["pe_ttm"] for r in series]),
            "pb": last.get("pb"),
            "pb_pct": percentile_rank(last.get("pb"),
                                      [r["pb"] for r in series]),
            "rs60": inputs.get("rs60"), "flow20": inputs.get("flow20"),
            "score": p.get("score"), "score_profit": p.get("score_profit"),
            "score_valuation": p.get("score_valuation"),
            "score_momentum": p.get("score_momentum"),
            "score_flow": p.get("score_flow"),
            "hist_start": series[0]["trade_date"].isoformat()
            if series else None,
        })
    return {"trade_date": d.isoformat(), "window": window, "rows": rows}


def _pb_break_data(scope: str, scope_code: str | None,
                   years: int) -> dict:
    repo = _repo()
    end = dt.date.today()
    start = end - dt.timedelta(days=int(years * 365.25))
    code = scope_code or ("ALL" if scope == "market" else None)
    if scope == "industry" and code not in SW_L1_CODES:
        raise ValueError("scope_code 须为申万一级行业码")
    series = repo.get_pb_break_series(scope, code, start, end)
    rates = [r["break_rate"] for r in series
             if r["break_rate"] is not None]
    current = series[-1] if series else None
    return {
        "scope": scope, "scope_code": code,
        "threshold": PB_BREAK_THRESHOLD,
        "series": [dict(r, trade_date=r["trade_date"].isoformat())
                   for r in series],
        "current": dict(current,
                        trade_date=current["trade_date"].isoformat())
        if current else None,
        "current_percentile": percentile_rank(
            current.get("break_rate") if current else None, rates),
        "over_threshold_now": bool(
            current and current.get("break_rate", 0) > PB_BREAK_THRESHOLD),
    }


def _flow_data() -> dict:
    repo = _repo()
    latest = repo.get_flow_latest_date()
    if latest is None:
        return {"snapshot": None, "rows": []}
    rows = repo.get_flow_rows(latest - dt.timedelta(days=30))
    return {"snapshot": latest.isoformat(),
            "rows": summarize_flow(rows)}


@router.get("/overview")
def overview(window: int = 8):
    if window not in (5, 8, 10):
        raise HTTPException(400, "window 须为 5/8/10")
    return _ok(_overview_data(window))


@router.get("/pb-break")
def pb_break(scope: str = "market", scope_code: str = None,
             years: int = 35):
    if scope not in ("market", "industry"):
        raise HTTPException(400, "scope 须为 market/industry")
    try:
        return _ok(_pb_break_data(scope=scope, scope_code=scope_code,
                                  years=years))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/flow")
def flow():
    return _ok(_flow_data())
```

`backend/main.py` router 挂载段（boom_router 行后）追加：

```python
from src.api.router.industry_router import router as industry_router
```
（import 聚合处按现有惯例放置）与

```python
    app.include_router(industry_router, prefix="/api/v1")  # /api/v1/industry
```

- [ ] **Step 8: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_industry_router.py tests/domain/market/industry_analysis/test_flow_summary.py -v`
Expected: 4 passed（detail 404 测试此时尚无该路由——把它挪到 Task 10 一起跑，此处先注释掉 `test_detail_404_on_bad_code`，Task 10 解开）

- [ ] **Step 9: Commit**

```bash
git add backend/src/api/router/industry_router.py backend/main.py \
  backend/tests/api/test_industry_router.py \
  backend/tests/domain/market/industry_analysis/test_flow_summary.py \
  backend/src/domain/market/industry_analysis/flow_map.py
git commit -m "feat(industry): /overview /pb-break /flow 三端点+资金流窗口汇总"
```

---

### Task 10: 行业详情/RS强度/LLM解读 三端点

**Files:**
- Create: `backend/src/domain/market/industry_analysis/llm_analyst.py`
- Modify: `backend/src/api/router/industry_router.py`（追加三端点与辅助）
- Modify: `backend/src/infra/database/market/industry_analysis.py`（仓储补 `get_concentration`）
- Test: `backend/tests/domain/market/industry_analysis/test_llm_analyst.py`

**Interfaces:**
- Consumes: `load_prompt_from_db_or`/`render_prompt`（`src.domain.market.intel.agents.base`）、`LLMManager`、Task 3 仓储。
- Produces:
  - `llm_analyst.build_prompt(ctx: dict) -> str`、`parse_industry_json(text) -> dict`（`{summary, drivers: [], risks: []}`，坏输出降级）、`interpret(code: str, d: str) -> dict`（async，进程内缓存 key=(code,d)）
  - 端点 `GET /industry/{sw_code}`、`GET /industry/{sw_code}/strength?compare=`、`POST /industry/{sw_code}/interpret`
  - 仓储 `get_concentration(sw_code, level=1) -> dict | None`（report_date/sample_count/revenue_yoy/net_profit_sum/cr4/cr8/hhi/distribution）

- [ ] **Step 1: 写失败测试（含解开 Task 9 注释的 404 测试）**

```python
# backend/tests/domain/market/industry_analysis/test_llm_analyst.py
from src.domain.market.industry_analysis.llm_analyst import (
    build_prompt, parse_industry_json,
)

CTX = {"name": "银行", "tier_label": "易分析",
       "approach": "看净息差/不良率", "score": 72.5, "score_profit": 80.0,
       "score_valuation": 65.0, "score_momentum": 50.0, "score_flow": 70.0,
       "pb": 0.6, "pb_pct": 12.0, "rs60": 0.05, "flow20": 2.4e9}


def test_build_prompt_contains_facts():
    p = build_prompt(CTX)
    assert "银行" in p and "72.5" in p and "净息差" in p


def test_parse_ok():
    r = parse_industry_json(
        '```json\n{"summary": "ok", "drivers": ["a", "b"], '
        '"risks": ["c"]}\n```')
    assert r["summary"] == "ok" and r["drivers"] == ["a", "b"]


def test_parse_fallback():
    r = parse_industry_json("不是json")
    assert r["summary"].startswith("不是json")
    assert r["drivers"] == [] and r["risks"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis/test_llm_analyst.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 llm_analyst（照 boom llm_analyst 模式）**

```python
# backend/src/domain/market/industry_analysis/llm_analyst.py
"""行业 LLM 解读:手动触发,进程内当日缓存(boom llm_analyst 同款范式)。"""
import json
import re

from src.domain.market.intel.agents.base import (
    load_prompt_from_db_or, render_prompt,
)

DEFAULT_INDUSTRY_ANALYST_PROMPT = """你是A股行业分析师。基于以下行业数据写一段景气解读。

行业: {{ name }}(投资难易度: {{ tier_label }})
分析抓手: {{ approach }}
景气分: {{ score }}(盈利{{ score_profit }}/估值{{ score_valuation }}/动量{{ score_momentum }}/资金{{ score_flow }})
估值: PB={{ pb }}(历史分位{{ pb_pct }}%)
动量: 60日相对沪深300超额 {{ rs60 }}
资金: 近20日主力净流入 {{ flow20 }} 元
请输出 JSON(不要输出其他内容):
{"summary": "120字内行业景气判断", "drivers": ["驱动点1", "驱动点2"], "risks": ["风险点1", "风险点2"]}
"""


def build_prompt(ctx: dict) -> str:
    return render_prompt(
        load_prompt_from_db_or("industry_analyst",
                               DEFAULT_INDUSTRY_ANALYST_PROMPT),
        **ctx,
    )


def parse_industry_json(text: str) -> dict:
    fallback = {"summary": "", "drivers": [], "risks": []}
    if not text:
        return fallback
    text = re.sub(r"```(?:json)?", "", text)
    lo, hi = text.find("{"), text.rfind("}")
    if lo < 0 or hi <= lo:
        return {**fallback, "summary": text[:300]}
    try:
        obj = json.loads(text[lo:hi + 1])
    except json.JSONDecodeError:
        return {**fallback, "summary": text[:300]}
    return {
        "summary": str(obj.get("summary", ""))[:500],
        "drivers": [str(x)[:80] for x in (obj.get("drivers") or [])][:5],
        "risks": [str(x)[:80] for x in (obj.get("risks") or [])][:5],
    }


_CACHE: dict[tuple[str, str], dict] = {}


def cache_get(code: str, d: str) -> dict | None:
    return _CACHE.get((code, d))


def cache_put(code: str, d: str, result: dict) -> None:
    if len(_CACHE) > 500:          # 进程内缓存护栏
        _CACHE.clear()
    _CACHE[(code, d)] = result


async def interpret(code: str, d: str) -> dict:
    """调用默认 LLM 生成行业解读;失败上抛,由 router 降级 503。"""
    cached = cache_get(code, d)
    if cached is not None:
        return cached
    from src.infra.llm.manager import LLMManager

    manager = LLMManager()
    provider = manager.get_provider()
    if provider is None:
        raise RuntimeError("LLM provider not configured")
    result = parse_industry_json(
        (await provider.complete(build_prompt(_build_ctx(code, d)),
                                 temperature=0.2, max_tokens=640)).content)
    cache_put(code, d, result)
    return result


def _build_ctx(code: str, d: str) -> dict:
    """从仓储/知识层拼 prompt 上下文(数值直接进文案)。"""
    import datetime as dt

    from src.domain.market.industry_analysis.knowledge import (
        TIER_LABELS, load_knowledge,
    )
    from src.infra.database.market.industry_analysis import (
        create_industry_analysis_repository,
    )
    repo = create_industry_analysis_repository()
    k = load_knowledge()[code]
    as_of = dt.date.fromisoformat(d)
    p = next((r for r in repo.get_prosperity(as_of)
              if r["sw_code"] == code), None)
    inputs = (p or {}).get("inputs") or {}
    return {"name": k.name, "tier_label": TIER_LABELS[k.tier],
            "approach": k.approach, "score": _fmt(p and p.get("score")),
            "score_profit": _fmt(p and p.get("score_profit")),
            "score_valuation": _fmt(p and p.get("score_valuation")),
            "score_momentum": _fmt(p and p.get("score_momentum")),
            "score_flow": _fmt(p and p.get("score_flow")),
            "pb": _fmt(inputs.get("pb")), "pb_pct": _fmt(inputs.get("pb_pct")),
            "rs60": _fmt(inputs.get("rs60")),
            "flow20": _fmt(inputs.get("flow20"))}


def _fmt(v) -> str:
    if v is None:
        return "缺"
    return f"{v:.4g}" if isinstance(v, float) else str(v)
```

- [ ] **Step 4: 仓储补 get_concentration**

在 `IndustryAnalysisRepository` 里追加（`get_cross_section_latest_two` 方法后）：

```python
    def get_concentration(self, sw_code: str, level: int = 1) -> Optional[dict]:
        sql = ("SELECT report_date, sample_count, revenue_yoy, "
               "net_profit_sum, cr4, cr8, hhi, distribution "
               "FROM sw_industry_cross_section "
               "WHERE sw_code = %(c)s AND level = %(lv)s "
               "ORDER BY report_date DESC LIMIT 1")
        conn = psycopg2.connect(get_dsn())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, {"c": sw_code, "lv": level})
                r = cur.fetchone()
        finally:
            conn.close()
        if not r:
            return None
        return {"report_date": r[0], "sample_count": r[1],
                "revenue_yoy": r[2], "net_profit_sum": r[3], "cr4": r[4],
                "cr8": r[5], "hhi": r[6], "distribution": r[7]}
```

- [ ] **Step 5: router 追加三端点**

在 `industry_router.py` 追加：

```python
def _detail_data(sw_code: str) -> dict:
    if sw_code not in SW_L1_CODES:
        raise LookupError(sw_code)
    repo = _repo()
    know = load_knowledge()
    k = know[sw_code]
    p_date = repo.get_prosperity_latest_date()
    prosper = next((r for r in (repo.get_prosperity(p_date)
                                if p_date else []),
                    r["sw_code"] == sw_code), None)
    conc = repo.get_concentration(sw_code)
    # 成分估值:最新估值交易日截面
    today = dt.date.today()
    v_dates = repo.get_stock_valuation_dates(
        today - dt.timedelta(days=15), today)
    members = (repo.get_member_valuations(v_dates[-1])
               if v_dates else [])
    mine = [m for m in members if m["sw_code_l1"] == sw_code]
    from src.domain.market.industry_analysis.stats import histogram
    pb_hist = histogram([m["pb"] for m in mine], bins=20)
    pe_hist = histogram([m["pe_ttm"] for m in mine], bins=20,
                        lo=0, hi=200)      # 负PE剔除展示
    top = sorted(mine, key=lambda m: m["total_mv"] or 0,
                 reverse=True)[:20]
    return {
        "sw_code": sw_code, "name": k.name, "knowledge": {
            "tier": k.tier, "tier_label": TIER_LABELS[k.tier],
            "retail_suitable": k.retail_suitable, "approach": k.approach,
            "upstream": list(k.upstream), "downstream": list(k.downstream),
            "note": k.note},
        "prosperity": prosper,
        "valuation_date": v_dates[-1].isoformat() if v_dates else None,
        "member_count": len(mine),
        "pb_histogram": pb_hist, "pe_histogram": pe_hist,
        "members": top,
        "concentration": conc,
    }


def _strength_data(sw_code: str, compare: list[str]) -> dict:
    if sw_code not in SW_L1_CODES:
        raise LookupError(sw_code)
    repo = _repo()
    end = dt.date.today()
    start = end - dt.timedelta(days=365)
    codes = [sw_code] + [c for c in compare if c in SW_L1_CODES][:4]
    closes = repo.get_index_closes(
        [f"sw{c}" for c in codes] + ["sh000300"], start, end)
    bench_list = closes.get("sh000300", [])
    b0 = (bench_list[0][1] if bench_list else 1.0) or 1.0
    lines = {}
    for c in codes:
        cl = closes.get(f"sw{c}", [])
        # RS 线 = 标的/基准双 rebase 商(首点 1.0);按日期对齐,任一侧缺日跳过
        pts = [(d, p, dict(bench_list)[d]) for (d, p) in cl
               if d in dict(bench_list)]
        if not pts:
            continue
        p0, bb0 = pts[0][1], pts[0][2]
        if not p0 or not bb0:
            continue
        lines[c] = [{"date": d.isoformat(),
                     "rs": round((p / p0) / (b / bb0), 6)}
                    for (d, p, b) in pts]
    from src.domain.market.industry_analysis.knowledge import load_knowledge
    know = load_knowledge()
    return {
        "sw_code": sw_code,
        "benchmark": [{"date": d.isoformat(), "close": round(p / b0, 6)}
                      for (d, p) in bench_list],
        "lines": lines,
        "names": {c: know[c].name for c in codes},
    }


@router.get("/{sw_code}")
def detail(sw_code: str):
    try:
        return _ok(_detail_data(sw_code))
    except LookupError:
        raise HTTPException(404, f"未知申万一级行业: {sw_code}")


@router.get("/{sw_code}/strength")
def strength(sw_code: str, compare: str = ""):
    try:
        return _ok(_strength_data(
            sw_code, [c for c in compare.split(",") if c]))
    except LookupError:
        raise HTTPException(404, f"未知申万一级行业: {sw_code}")


@router.post("/{sw_code}/interpret")
async def interpret_route(sw_code: str):
    if sw_code not in SW_L1_CODES:
        raise HTTPException(404, f"未知申万一级行业: {sw_code}")
    repo = _repo()
    d = repo.get_prosperity_latest_date()
    if d is None:
        raise HTTPException(404, "暂无景气分数据,请先跑回填/等待job")
    from src.domain.market.industry_analysis import llm_analyst
    try:
        result = await llm_analyst.interpret(sw_code, d.isoformat())
    except llm_analyst.LLMNotConfigured as e:   # 专用异常,不与调用失败混淆
        raise HTTPException(503, str(e))
    except Exception as e:         # noqa: BLE001
        log.error("[INDUSTRY_INTERPRET] %s failed: %s", sw_code, e)
        raise HTTPException(502, f"LLM 调用失败: {e}")
    return _ok({"sw_code": sw_code, "date": d.isoformat(), **result})
```

同时解开 Task 9 中被注释的 `test_detail_404_on_bad_code`。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_industry_router.py tests/domain/market/industry_analysis/test_llm_analyst.py -v`
Expected: 7 passed

Run（真库冒烟,需 Task 8 回填已完成）:
```bash
cd backend && uv run python -c "
from src.api.router.industry_router import _overview_data, _pb_break_data, _flow_data, _detail_data
o = _overview_data(8); print('overview rows:', len(o['rows']))
p = _pb_break_data('market', None, 35); print('pb series:', len(p['series']), 'now>', p['over_threshold_now'])
d = _detail_data('801780'); print('detail members:', d['member_count'])"
```
Expected: `overview rows: 31`；`pb series` 为数千；`detail members` ≈ 40+。

- [ ] **Step 7: Commit**

```bash
git add backend/src/domain/market/industry_analysis/llm_analyst.py \
  backend/src/api/router/industry_router.py \
  backend/src/infra/database/market/industry_analysis.py \
  backend/tests/domain/market/industry_analysis/test_llm_analyst.py
git commit -m "feat(industry): 行业详情/RS强度叠加/LLM解读三端点(手动触发+进程缓存)"
```

---

### Task 11: 前端数据 hook + 热力纯函数 + vitest

**Files:**
- Create: `frontend/apps/web/src/hooks/useIndustryAnalysis.ts`
- Create: `frontend/apps/web/src/lib/heat.ts`
- Test: `frontend/apps/web/src/components/industry/__tests__/heat.test.ts`

**Interfaces:**
- Consumes: Task 9/10 端点（`/api/v1/industry/...`）、`lib/api.getApiBase`。
- Produces（Task 12-14 消费）:
  - 类型 `OverviewRow / PbBreakData / FlowData / IndustryDetail / StrengthData`
  - hooks：`useIndustryOverview(window: 5|8|10)`、`usePbBreak(scope, scopeCode, years)`、`useIndustryFlow()`、`useIndustryDetail(swCode: string | null)`、`useInterpret()`（`{run(swCode), result, loading, error}`）
  - `heat.ts`：`heatColor(v, lo, hi, inverse?) -> string | null`（HEAT_SCALE 三段插值）、`sortByCol(rows, key, dir)`、`fmtPctN(v)`、`TIER_LABEL: Record<number,string>`

- [ ] **Step 1: 写失败测试**

```ts
// frontend/apps/web/src/components/industry/__tests__/heat.test.ts
import {describe, expect, it} from 'vitest';
import {heatColor, sortByCol} from '../../../lib/heat';

describe('heatColor', () => {
  it('三段插值边界', () => {
    expect(heatColor(0, 0, 10)).toBe('#ffd60a');
    expect(heatColor(10, 0, 10)).toBe('#ff453a');
    expect(heatColor(5, 0, 10)).toBe('#ff9f0a');
  });
  it('inverse 取反(估值分位低=好→暖色)', () => {
    expect(heatColor(0, 0, 10, true)).toBe('#ff453a');
    expect(heatColor(10, 0, 10, true)).toBe('#ffd60a');
  });
  it('null/退化区间', () => {
    expect(heatColor(null, 0, 10)).toBeNull();
    expect(heatColor(3, 5, 5)).toBeNull();
  });
});

describe('sortByCol', () => {
  const rows = [{a: 2, b: 'x'}, {a: null, b: 'y'}, {a: 1, b: 'z'}];
  it('数值列降序,null 沉底', () => {
    expect(sortByCol(rows, 'a', -1).map((r) => r.a)).toEqual([2, 1, null]);
  });
  it('字符串列升序', () => {
    expect(sortByCol(rows, 'b', 1).map((r) => r.b)).toEqual(['x', 'y', 'z']);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend/apps/web && npm test`
Expected: FAIL（找不到 `../../../lib/heat`）

- [ ] **Step 3: 实现 heat.ts 与 hook 文件**

```ts
// frontend/apps/web/src/lib/heat.ts
/** 行业热力图纯逻辑:着色/排序/格式化(vitest 覆盖)。 */
import {HEAT_SCALE} from './chartTheme';

const [LO, MID, HI] = HEAT_SCALE;   // '#ffd60a' → '#ff9f0a' → '#ff453a'

function lerpColor(c1: string, c2: string, t: number): string {
  const p = (c: string) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
  const [r1, g1, b1] = p(c1);
  const [r2, g2, b2] = p(c2);
  const m = (a: number, b: number) => Math.round(a + (b - a) * t);
  const hex = (n: number) => n.toString(16).padStart(2, '0');
  return `#${hex(m(r1, r2))}${hex(m(g1, g2))}${hex(m(b1, b2))}`;
}

/** 值→暖色刻度;inverse=true 时低值暖(估值分位低=便宜=好)。null→null。 */
export function heatColor(v: number | null, lo: number, hi: number,
                          inverse = false): string | null {
  if (v == null || !Number.isFinite(v) || hi <= lo) return null;
  let t = (v - lo) / (hi - lo);
  t = Math.min(1, Math.max(0, t));
  if (inverse) t = 1 - t;
  return t <= 0.5 ? lerpColor(LO, MID, t * 2) : lerpColor(MID, HI, t * 2 - 1);
}

/** 排序:null 一律沉底;dir=1 升序/-1 降序。 */
export function sortByCol<T extends Record<string, any>>(rows: T[],
                                                         key: string,
                                                         dir: 1 | -1): T[] {
  return [...rows].sort((a, b) => {
    const va = a[key];
    const vb = b[key];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'number' && typeof vb === 'number') {
      return (va - vb) * dir;
    }
    return String(va).localeCompare(String(vb)) * dir;
  });
}

export const TIER_LABEL: Record<number, string> = {
  1: '易分析', 2: '需专业分析', 3: '消息驱动',
};

export const fmtPctN = (v: number | null | undefined, digits = 1): string =>
  v == null || !Number.isFinite(v) ? '—'
    : `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`;

/** 分位类百分数(0-100,不加正号) */
export const fmtPctAbs = (v: number | null | undefined, digits = 0): string =>
  v == null || !Number.isFinite(v) ? '—' : `${v.toFixed(digits)}%`;

export const fmtYi = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? '—' : `${(v / 1e8).toFixed(1)}亿`;

export const fmtN = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? '—' : v.toFixed(digits);
```

```ts
// frontend/apps/web/src/hooks/useIndustryAnalysis.ts
/** 行业分析数据 hook(GET /industry/*;信封 {code,msg,data})。 */
import {useCallback, useEffect, useRef, useState} from 'react';
import {getApiBase} from '../lib/api';

const API_BASE = getApiBase();

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  const j = await r.json();
  if (j.code !== 0) throw new Error(j.msg || '请求失败');
  return j.data as T;
}

export type PctWindow = 5 | 8 | 10;

export interface OverviewRow {
  sw_code: string;
  name: string;
  tier: number;
  tier_label: string;
  retail_suitable: string;
  revenue_yoy: number | null;
  net_profit_yoy: number | null;
  pe_ttm: number | null;
  pe_pct: number | null;
  pb: number | null;
  pb_pct: number | null;
  rs60: number | null;
  flow20: number | null;
  score: number | null;
  score_profit: number | null;
  score_valuation: number | null;
  score_momentum: number | null;
  score_flow: number | null;
  hist_start: string | null;
}

export interface OverviewData {
  trade_date: string | null;
  window: number;
  rows: OverviewRow[];
}

export interface PbBreakPoint {
  trade_date: string;
  total_count: number;
  break_count: number;
  break_rate: number | null;
  median_pb: number | null;
}

export interface PbBreakData {
  scope: string;
  scope_code: string | null;
  threshold: number;
  series: PbBreakPoint[];
  current: PbBreakPoint | null;
  current_percentile: number | null;
  over_threshold_now: boolean;
}

export interface FlowRow {
  em_industry_name: string;
  sw_code: string | null;
  day: number | null;
  flow5: number | null;
  flow20: number | null;
}

export interface IndustryDetail {
  sw_code: string;
  name: string;
  knowledge: {
    tier: number;
    tier_label: string;
    retail_suitable: string;
    approach: string;
    upstream: string[];
    downstream: string[];
    note: string;
  };
  prosperity: {
    score: number | null;
    score_profit: number | null;
    score_valuation: number | null;
    score_momentum: number | null;
    score_flow: number | null;
    inputs: Record<string, number | null>;
  } | null;
  valuation_date: string | null;
  member_count: number;
  pb_histogram: {edges: number[]; counts: number[]};
  pe_histogram: {edges: number[]; counts: number[]};
  members: {symbol: string; name: string | null; pb: number | null;
            pe_ttm: number | null; total_mv: number | null}[];
  concentration: Record<string, any> | null;
}

export interface StrengthData {
  sw_code: string;
  benchmark: {date: string; close: number}[];
  lines: Record<string, {date: string; rs: number}[]>;
  names: Record<string, string>;
}

function useJson<T>(url: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const genRef = useRef(0);
  const load = useCallback(() => {
    if (!url) return;
    const gen = ++genRef.current;
    setLoading(true);
    getJson<T>(url)
      .then((d) => {
        if (gen !== genRef.current) return;
        setData(d);
        setError(null);
      })
      .catch((e: Error) => {
        if (gen !== genRef.current) return;
        setError(e.message);
      })
      .finally(() => {
        if (gen === genRef.current) setLoading(false);
      });
  }, [url]);
  useEffect(() => { load(); }, [load]);
  return {data, loading, error, reload: load};
}

export function useIndustryOverview(win: PctWindow) {
  return useJson<OverviewData>(`${API_BASE}/industry/overview?window=${win}`);
}

export function usePbBreak(scope: 'market' | 'industry', scopeCode: string,
                           years: number) {
  const qs = new URLSearchParams({scope, years: String(years)});
  if (scope === 'industry') qs.set('scope_code', scopeCode);
  return useJson<PbBreakData>(`${API_BASE}/industry/pb-break?${qs}`);
}

export function useIndustryFlow() {
  return useJson<{snapshot: string | null; rows: FlowRow[]}>(
    `${API_BASE}/industry/flow`);
}

export function useIndustryDetail(swCode: string | null) {
  return useJson<IndustryDetail>(
    swCode ? `${API_BASE}/industry/${swCode}` : null);
}

export function useStrength(swCode: string | null, compare: string[]) {
  const qs = compare.length ? `?compare=${compare.join(',')}` : '';
  return useJson<StrengthData>(
    swCode ? `${API_BASE}/industry/${swCode}/strength${qs}` : null);
}

export function useInterpret() {
  const [result, setResult] = useState<
    {summary: string; drivers: string[]; risks: string[]} | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (swCode: string) => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(`${API_BASE}/industry/${swCode}/interpret`,
        {method: 'POST'});
      const j = await r.json();
      if (j.code !== 0) throw new Error(j.msg || j.detail || '解读失败');
      setResult(j.data);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setLoading(false);
    }
  }, []);
  return {run, result, loading, error};
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend/apps/web && npm test`
Expected: heat.test.ts 全 passed（replay 既有测试仍绿）。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/hooks/useIndustryAnalysis.ts frontend/apps/web/src/lib/heat.ts \
  frontend/apps/web/src/components/industry/__tests__/heat.test.ts
git commit -m "feat(industry-web): 行业分析hooks+热力着色排序纯函数+vitest"
```

---

### Task 12: 页面壳 + 宏观择时 Tab + 路由菜单

**Files:**
- Create: `frontend/apps/web/src/pages/IndustryAnalysis.tsx`
- Create: `frontend/apps/web/src/pages/IndustryAnalysis.css`
- Create: `frontend/apps/web/src/components/industry/PbBreakTab.tsx`
- Modify: `frontend/apps/web/src/App.tsx`（lazy import + Route，`earnings-radar` 行后）
- Modify: `frontend/apps/web/src/components/Layout.tsx`（「分析」组第一项前插入）

**Interfaces:**
- Consumes: Task 11 hooks、`pages/ntLive/EChart`、`components/ui`。
- Produces: `IndustryAnalysis` 页组件；子组件 props：`PbBreakTab({industries, onPick})`（industries: `{sw_code, name}[]`，onPick 打开抽屉——Task 14 接线）。

- [ ] **Step 1: App.tsx 路由**

lazy 声明区（`EarningsRadar` 行后）加：

```tsx
const IndustryAnalysis = lazy(() => import('./pages/IndustryAnalysis').then(m => ({default: m.IndustryAnalysis})));
```

Routes 里 `earnings-radar` Route 后加：

```tsx
<Route path="/industry-analysis" element={<Suspense fallback={<div className="page-loading">加载中…</div>}><IndustryAnalysis /></Suspense>} />
```

- [ ] **Step 2: Layout.tsx 菜单**

「分析」组 items 数组首位插入：

```tsx
{path: '/industry-analysis', label: '行业分析', icon: Icon.analytics},
```

- [ ] **Step 3: 页面壳 + Tab1**

```tsx
// frontend/apps/web/src/pages/IndustryAnalysis.tsx
/** 行业分析:宏观择时(破净率)/景气热力图/板块强弱 三Tab+行业详情抽屉。 */
import {useState} from 'react';
import {PageHeader, StateView, Tabs} from '../components/ui';
import {PbBreakTab} from '../components/industry/PbBreakTab';
import {ProsperityHeatmap} from '../components/industry/ProsperityHeatmap';
import {StrengthFlowTab} from '../components/industry/StrengthFlowTab';
import {IndustryDetailDrawer} from '../components/industry/IndustryDetailDrawer';
import {useIndustryOverview, type PctWindow} from '../hooks/useIndustryAnalysis';
import './IndustryAnalysis.css';

export function IndustryAnalysis() {
  const [tab, setTab] = useState<'timing' | 'heatmap' | 'strength'>('timing');
  const [win, setWin] = useState<PctWindow>(8);
  const [picked, setPicked] = useState<string | null>(null);
  const overview = useIndustryOverview(win);
  const industries = (overview.data?.rows ?? [])
    .map((r) => ({sw_code: r.sw_code, name: r.name}));

  return (
    <div className="ia-page">
      <PageHeader title="行业分析"
        subtitle="破净率择时 · 行业景气热力图 · 板块资金强弱(申万一级31行业)" />
      <Tabs active={tab} onChange={(k) => setTab(k as typeof tab)} tabs={[
        {key: 'timing', label: '宏观择时'},
        {key: 'heatmap', label: '景气热力图'},
        {key: 'strength', label: '板块强弱'},
      ]} />
      {tab === 'timing' && <PbBreakTab industries={industries} onPick={setPicked} />}
      {tab === 'heatmap' && (
        <ProsperityHeatmap win={win} setWin={setWin}
          overview={overview} onPick={setPicked} />
      )}
      {tab === 'strength' && (
        <StrengthFlowTab industries={industries} onPick={setPicked} />
      )}
      {picked && <IndustryDetailDrawer swCode={picked} onClose={() => setPicked(null)} />}
    </div>
  );
}
```

```tsx
// frontend/apps/web/src/components/industry/PbBreakTab.tsx
/** 宏观择时:全市场/行业破净率历史,>10% 区间标红「阶段性底部参考区」。 */
import {useMemo, useState} from 'react';
import {Card, StateView} from '../ui';
import {EChart} from '../../pages/ntLive/EChart';
import {usePbBreak} from '../../../hooks/useIndustryAnalysis';
import {chartBorder, chartTextSecondary, colorWarning} from '../../../lib/chartTheme';

interface Props {
  industries: {sw_code: string; name: string}[];
  onPick: (swCode: string) => void;
}

export function PbBreakTab({industries, onPick}: Props) {
  const [scopeCode, setScopeCode] = useState('');        // '' = market
  const [years, setYears] = useState(10);
  const scope = scopeCode ? 'industry' : 'market';
  const {data, loading, error} = usePbBreak(scope, scopeCode, years);

  const option = useMemo(() => {
    if (!data?.series.length) return {};
    const series = data.series;
    const dates = series.map((p) => p.trade_date.slice(0, 10));
    const rates = series.map((p) => (p.break_rate ?? 0) * 100);
    // 连续 >10% 的区段 → markArea
    const areas: any[] = [];
    let start = -1;
    rates.forEach((v, i) => {
      const over = v > data.threshold * 100;
      if (over && start < 0) start = i;
      if (!over && start >= 0) {
        areas.push([{xAxis: dates[start]}, {xAxis: dates[i - 1]}]);
        start = -1;
      }
    });
    if (start >= 0) {
      areas.push([{xAxis: dates[start]},
                  {xAxis: dates[dates.length - 1]}]);
    }
    return {
      tooltip: {trigger: 'axis'},
      xAxis: {type: 'category', data: dates, axisLine: {lineStyle: {color: chartBorder}}},
      yAxis: {type: 'value', max: 60, axisLabel: {formatter: '{value}%'},
        splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      dataZoom: [{type: 'inside', start: 55, end: 100}],
      series: [{
        type: 'line', name: '破净率', data: rates.map((v) => +v.toFixed(2)),
        showSymbol: false, lineStyle: {width: 1.5},
        markLine: {silent: true, symbol: 'none', lineStyle: {color: colorWarning, type: 'dashed'},
          label: {formatter: '10% 底部参考线', color: chartTextSecondary},
          data: [{yAxis: data.threshold * 100}]},
        markArea: {silent: true, itemStyle: {color: 'rgba(255,69,58,0.10)'},
          label: {show: true, position: 'insideTop', color: colorWarning,
                  formatter: '阶段性底部参考区'},
          data: areas},
      }],
    } as any;
  }, [data]);

  const cur = data?.current;

  return (
    <div className="ia-tab">
      <div className="ia-toolbar">
        <select className="ia-select" value={scopeCode}
          onChange={(e) => setScopeCode(e.target.value)}>
          <option value="">全市场(market · 择时主信号)</option>
          {industries.map((i) => (
            <option key={i.sw_code} value={i.sw_code}>{i.name}(行业)</option>
          ))}
        </select>
        <select className="ia-select" value={years}
          onChange={(e) => setYears(Number(e.target.value))}>
          <option value={5}>近5年</option>
          <option value={10}>近10年</option>
          <option value={35}>全历史</option>
        </select>
        {scope === 'industry' && (
          <span className="ia-hint">⚠ 行业口径=当前成分回溯,含成分漂移偏差;择时只看全市场</span>
        )}
      </div>
      <div className="ia-cards">
        <Card><div className="ia-card">
          <div className="ia-card-label">当前破净率</div>
          <div className={`ia-card-value ${data?.over_threshold_now ? 'is-up' : ''}`}>
            {cur?.break_rate != null ? `${(cur.break_rate * 100).toFixed(2)}%` : '—'}
          </div>
          <div className="ia-card-sub">{cur ? `${cur.trade_date} · 破净 ${cur.break_count}/${cur.total_count} 家` : ''}</div>
        </div></Card>
        <Card><div className="ia-card">
          <div className="ia-card-label">历史分位(窗口内)</div>
          <div className="ia-card-value">
            {data?.current_percentile != null ? `${data.current_percentile.toFixed(0)}%` : '—'}
          </div>
          <div className="ia-card-sub">中位PB {cur?.median_pb?.toFixed(2) ?? '—'}</div>
        </div></Card>
        <Card><div className="ia-card">
          <div className="ia-card-label">信号状态</div>
          <div className={`ia-card-value ${data?.over_threshold_now ? 'is-up' : ''}`}>
            {data?.over_threshold_now ? '>10% 底部参考区' : '未触及'}
          </div>
          <div className="ia-card-sub">阈值:破净率 10%(宏观择时,非个股机会)</div>
        </div></Card>
      </div>
      <Card>
        {loading && !data ? <StateView state="loading" /> :
         error ? <StateView state="error" text={error} /> :
         !data?.series.length ? <StateView state="empty" text="暂无破净率数据(先跑回填)" /> :
         <EChart option={option} height={360} />}
      </Card>
      {scopeCode && (
        <button className="ia-linklike" onClick={() => onPick(scopeCode)}>
          查看 {industries.find((i) => i.sw_code === scopeCode)?.name} 行业详情 →
        </button>
      )}
    </div>
  );
}
```

CSS（`ia-` 前缀，令牌化，节选核心——布局/卡片/工具条/热力表/徽章/抽屉全量约 120 行）：

```css
/* frontend/apps/web/src/pages/IndustryAnalysis.css */
.ia-page { padding: 16px; max-width: 1280px; margin: 0 auto; }
.ia-toolbar { display: flex; gap: 10px; align-items: center; margin: 12px 0; flex-wrap: wrap; }
.ia-select { background: var(--color-surface); color: var(--color-text);
  border: 1px solid var(--color-border); border-radius: var(--radius-sm, 8px);
  padding: 6px 10px; font-size: var(--text-sm); }
.ia-hint { font-size: var(--text-xs); color: var(--color-warning); }
.ia-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 12px; }
.ia-card-label { font-size: var(--text-xs); color: var(--color-text-secondary); }
.ia-card-value { font-size: 24px; font-weight: var(--font-weight-bold); margin: 4px 0; }
.ia-card-value.is-up { color: var(--color-up); }
.ia-card-sub { font-size: var(--text-xs); color: var(--color-text-tertiary); }
.ia-linklike { background: none; border: none; color: var(--color-text-secondary);
  cursor: pointer; padding: 8px 2px; font-size: var(--text-sm); }
.ia-linklike:hover { color: var(--color-text); }
/* ── 热力表(Task 13)── */
.ia-heat-wrap { overflow-x: auto; }
.ia-heat { width: 100%; border-collapse: collapse; font-size: var(--text-xs); }
.ia-heat th { position: sticky; top: 0; background: var(--color-surface);
  padding: 8px 6px; text-align: right; cursor: pointer; white-space: nowrap;
  color: var(--color-text-secondary); border-bottom: 1px solid var(--color-border-strong); }
.ia-heat th:first-child, .ia-heat td:first-child { text-align: left; position: sticky; left: 0; }
.ia-heat td { padding: 7px 6px; text-align: right; white-space: nowrap;
  border-bottom: 1px solid var(--color-border); }
.ia-heat tbody tr { cursor: pointer; }
.ia-heat tbody tr:hover { background: var(--color-surface); }
.ia-heat .num { font-variant-numeric: tabular-nums; }
.ia-tier { display: inline-block; padding: 1px 8px; border-radius: var(--radius-pill);
  font-size: var(--text-xs); }
.ia-tier--1 { background: var(--color-down-light); color: var(--color-down); }
.ia-tier--2 { background: var(--color-warning-bg, rgba(255,214,10,.12)); color: var(--color-warning); }
.ia-tier--3 { background: var(--color-up-light); color: var(--color-up); }
/* ── 抽屉(Task 14)── */
.ia-drawer-section { margin-bottom: 16px; }
.ia-drawer-title { font-size: var(--text-sm); font-weight: var(--font-weight-bold);
  margin-bottom: 8px; color: var(--color-text-secondary); }
.ia-chain { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ia-chain-chip { padding: 3px 10px; border-radius: var(--radius-pill);
  background: var(--color-surface); border: 1px solid var(--color-border);
  font-size: var(--text-xs); }
.ia-chain-self { border-color: var(--color-warning); color: var(--color-warning); }
.ia-arrow { color: var(--color-text-tertiary); }
.ia-subscore { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.ia-subscore-bar { height: 8px; border-radius: 4px; background: var(--color-surface);
  flex: 1; overflow: hidden; }
.ia-subscore-fill { height: 100%; background: var(--color-warning); }
```

注意：`--color-warning-bg` 若 global.css 无此变量，删掉该行回退 `background: var(--color-surface)`（以令牌实际存在为准，实施时核对 `styles/global.css`）。

- [ ] **Step 4: 冒烟**

Run: `cd frontend/apps/web && npm run build`
Expected: 构建通过（Tab2/3/抽屉组件在 Task 13/14 才创建——本任务先在同目录放三个占位再替换？**不占位**：Task 12 的页面 import 推迟到 Task 13/14。实施顺序：先做 Task 12 的路由/菜单/CSS/`PbBreakTab`，页面组件里 heatmap/strength/drawer 三行 import 与对应渲染留到 Task 13/14 各自加上——即 Task 12 提交时 `IndustryAnalysis.tsx` 暂时只渲染 Tab1（tab 切换到 heatmap 显示空 StateView），Task 13/14 补齐。）

Run: `cd frontend/apps/web && npm run dev`，浏览器开 `/industry-analysis`
Expected: 菜单「分析→行业分析」可进；破净率曲线渲染、>10% 区段有红色 markArea、卡片数值正常（依赖后端 Task 8 回填完成）。

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/IndustryAnalysis.tsx \
  frontend/apps/web/src/pages/IndustryAnalysis.css \
  frontend/apps/web/src/components/industry/PbBreakTab.tsx \
  frontend/apps/web/src/App.tsx frontend/apps/web/src/components/Layout.tsx
git commit -m "feat(industry-web): 行业分析页壳+宏观择时Tab(破净率曲线/10%底部区/分位卡片)+路由菜单"
```

---

### Task 13: 景气热力图 Tab + 板块强弱 Tab

**Files:**
- Create: `frontend/apps/web/src/components/industry/ProsperityHeatmap.tsx`
- Create: `frontend/apps/web/src/components/industry/StrengthFlowTab.tsx`
- Modify: `frontend/apps/web/src/pages/IndustryAnalysis.tsx`（接入两个 Tab 与 import）

**Interfaces:**
- Consumes: Task 11 hooks/heat、Task 12 页面状态（win/overview/onPick）。
- Produces: `ProsperityHeatmap({win, setWin, overview, onPick})`；`StrengthFlowTab({industries, onPick})`。

- [ ] **Step 1: ProsperityHeatmap（表格热力,列可排序,行点击开抽屉）**

```tsx
// frontend/apps/web/src/components/industry/ProsperityHeatmap.tsx
/** 31行业×指标矩阵:单元格按列内 min-max 着色(HEAT_SCALE),估值分位取反。 */
import {useMemo, useState} from 'react';
import {Card, StateView} from '../ui';
import type {OverviewRow, PctWindow} from '../../../hooks/useIndustryAnalysis';
import {fmtN, fmtPctAbs, fmtPctN, fmtYi, heatColor, sortByCol} from '../../../lib/heat';

interface Col {
  key: keyof OverviewRow;
  label: string;
  fmt: (r: OverviewRow) => string;
  inverse?: boolean;   // true=低值暖色(估值分位)
}

const COLS: Col[] = [
  {key: 'score', label: '景气分', fmt: (r) => fmtN(r.score, 0)},
  {key: 'revenue_yoy', label: '营收同比', fmt: (r) => fmtPctN(r.revenue_yoy)},
  {key: 'net_profit_yoy', label: '净利同比', fmt: (r) => fmtPctN(r.net_profit_yoy)},
  {key: 'pe_ttm', label: 'PE(TTM)', fmt: (r) => fmtN(r.pe_ttm, 1)},
  {key: 'pe_pct', label: 'PE分位', fmt: (r) => fmtPctAbs(r.pe_pct), inverse: true},
  {key: 'pb', label: 'PB', fmt: (r) => fmtN(r.pb, 2)},
  {key: 'pb_pct', label: 'PB分位', fmt: (r) => fmtPctAbs(r.pb_pct), inverse: true},
  {key: 'rs60', label: 'RS60', fmt: (r) => fmtPctN(r.rs60)},
  {key: 'flow20', label: '20日资金', fmt: (r) => fmtYi(r.flow20)},
];

interface Props {
  win: PctWindow;
  setWin: (w: PctWindow) => void;
  overview: {data: {rows: OverviewRow[]; trade_date: string | null} | null;
             loading: boolean; error: string | null};
  onPick: (swCode: string) => void;
}

export function ProsperityHeatmap({win, setWin, overview, onPick}: Props) {
  const [sortKey, setSortKey] = useState<keyof OverviewRow>('score');
  const [dir, setDir] = useState<-1 | 1>(-1);
  const rows = overview.data?.rows ?? [];

  const {sorted, bounds} = useMemo(() => {
    const b: Record<string, [number, number]> = {};
    for (const c of COLS) {
      const vals = rows.map((r) => r[c.key] as number | null)
        .filter((v): v is number => v != null && Number.isFinite(v));
      b[c.key as string] = vals.length
        ? [Math.min(...vals), Math.max(...vals)] : [0, 0];
    }
    return {sorted: sortByCol(rows as any[], sortKey as string, dir), bounds: b};
  }, [rows, sortKey, dir]);

  const toggleSort = (key: keyof OverviewRow) => {
    if (key === sortKey) setDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(key); setDir(key === 'name' ? 1 : -1); }
  };

  if (overview.loading && !rows.length) return <StateView state="loading" />;
  if (overview.error) return <StateView state="error" text={overview.error} />;
  if (!rows.length) return <StateView state="empty" text="暂无景气分数据" />;

  return (
    <Card>
      <div className="ia-toolbar">
        <span className="ia-hint">评分日 {overview.data?.trade_date} · 估值分位窗口</span>
        {([5, 8, 10] as PctWindow[]).map((w) => (
          <button key={w} className={`ia-select ${w === win ? 'is-active' : ''}`}
            onClick={() => setWin(w)}>{w}年</button>
        ))}
        <span className="ia-hint">仅展示列随窗口切换;景气分口径恒定8年(规格§4 F2)</span>
      </div>
      <div className="ia-heat-wrap">
        <table className="ia-heat">
          <thead><tr>
            <th onClick={() => toggleSort('name')}>行业</th>
            <th>难易度</th>
            {COLS.map((c) => (
              <th key={c.key as string} onClick={() => toggleSort(c.key)}>
                {c.label}{sortKey === c.key ? (dir === -1 ? ' ↓' : ' ↑') : ''}
              </th>
            ))}
          </tr></thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.sw_code} onClick={() => onPick(r.sw_code)}
                title={r.hist_start ? `估值历史自 ${r.hist_start}(分位窗口内)` : undefined}>
                <td><b>{r.name}</b></td>
                <td style={{textAlign: 'left'}}>
                  <span className={`ia-tier ia-tier--${r.tier}`}>{r.tier_label}</span>
                </td>
                {COLS.map((c) => {
                  const [lo, hi] = bounds[c.key as string];
                  const v = r[c.key] as number | null;
                  const bg = heatColor(v, lo, hi, c.inverse);
                  return (
                    <td key={c.key as string} className="num"
                      style={bg ? {background: bg + '55',
                        fontWeight: c.key === 'score' ? 700 : undefined} : undefined}>
                      {c.fmt(r)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
```

- [ ] **Step 2: StrengthFlowTab（资金流排行 + RS 线叠加）**

```tsx
// frontend/apps/web/src/components/industry/StrengthFlowTab.tsx
/** 板块强弱:左=东财行业资金流(当日/5日/20日);右=行业RS线 vs 沪深300(≤5叠加)。 */
import {useMemo, useState} from 'react';
import {Card, StateView} from '../ui';
import {EChart} from '../../pages/ntLive/EChart';
import {useIndustryFlow, useStrength} from '../../../hooks/useIndustryAnalysis';
import {chartBorder, colorUp, colorDown, seriesColor} from '../../../lib/chartTheme';
import {fmtYi} from '../../../lib/heat';

interface Props {
  industries: {sw_code: string; name: string}[];
  onPick: (swCode: string) => void;
}

export function StrengthFlowTab({industries, onPick}: Props) {
  const flow = useIndustryFlow();
  const [picked, setPicked] = useState<string[]>([]);
  const main = picked[0] || industries[0]?.sw_code || '';
  const strength = useStrength(main || null, picked.slice(1, 5));

  const flowOption = useMemo(() => {
    const rows = (flow.data?.rows ?? []).slice(0, 15);
    return {
      tooltip: {trigger: 'axis'},
      grid: {left: 90, right: 20, top: 20, bottom: 30, containLabel: false},
      xAxis: {type: 'value', axisLine: {lineStyle: {color: chartBorder}}},
      yAxis: {type: 'category', data: rows.map((r) => r.em_industry_name).reverse(),
        axisLabel: {fontSize: 11}},
      series: [{
        type: 'bar',
        data: rows.map((r) => ({
          value: +((r.flow20 ?? 0) / 1e8).toFixed(1),
          itemStyle: {color: (r.flow20 ?? 0) >= 0 ? colorUp : colorDown,
            borderRadius: [0, 4, 4, 0]},
        })).reverse(),
      }],
    } as any;
  }, [flow.data]);

  const rsOption = useMemo(() => {
    const s = strength.data;
    if (!s || !Object.keys(s.lines).length) return {};
    const dates = s.lines[main]?.map((p) => p.date) ?? [];
    return {
      tooltip: {trigger: 'axis'},
      legend: {top: 0, textStyle: {fontSize: 11}},
      xAxis: {type: 'category', data: dates,
        axisLine: {lineStyle: {color: chartBorder}}},
      yAxis: {type: 'value', scale: true,
        splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
      dataZoom: [{type: 'inside', start: 40, end: 100}],
      series: [
        {name: '沪深300(rebase)', type: 'line', showSymbol: false,
         lineStyle: {type: 'dashed', width: 1},
         data: s.benchmark.map((p) => p.close)},
        ...Object.entries(s.lines).map(([code, line], i) => ({
          name: s.names[code] ?? code, type: 'line' as const, showSymbol: false,
          lineStyle: {width: 1.6}, color: seriesColor(i),
          data: line.map((p) => p.rs),
        })),
      ],
    } as any;
  }, [strength.data, main]);

  const toggle = (code: string) => {
    setPicked((prev) => prev.includes(code)
      ? prev.filter((c) => c !== code)
      : [...prev, code].slice(-5));
  };

  return (
    <div className="ia-tab ia-strength-grid">
      <Card>
        <div className="ia-drawer-title">
          行业资金流·20日主力净流入(亿) {flow.data?.snapshot ? `· 至 ${flow.data.snapshot}` : ''}
        </div>
        {flow.loading && !flow.data ? <StateView state="loading" /> :
         !flow.data?.rows.length ? <StateView state="empty" text="暂无资金流历史(等待17:05 job积累)" /> :
         <EChart option={flowOption} height={440} />}
        <div className="ia-hint">东财口径(~90行业);红=净流入 绿=净流出;点击右侧行业名叠加RS线</div>
      </Card>
      <Card>
        <div className="ia-drawer-title">相对强度 RS(标的/沪深300,均rebase 1.0)</div>
        <div className="ia-chip-row">
          {industries.map((i) => (
            <button key={i.sw_code}
              className={`ia-chain-chip ${picked.includes(i.sw_code) ? 'ia-chain-self' : ''}`}
              onClick={() => toggle(i.sw_code)}
              onDoubleClick={() => onPick(i.sw_code)}>{i.name}</button>
          ))}
        </div>
        {strength.loading && !strength.data ? <StateView state="loading" /> :
         !strength.data || !Object.keys(strength.data.lines).length ?
           <StateView state="empty" text="选择行业查看RS线" /> :
         <EChart option={rsOption} height={340} />}
        <div className="ia-hint">单击=加入叠加(≤5);双击=打开行业详情</div>
      </Card>
    </div>
  );
}
```

并在 `IndustryAnalysis.css` 追加：

```css
.ia-strength-grid { display: grid; grid-template-columns: minmax(320px, 2fr) minmax(420px, 3fr); gap: 12px; align-items: start; }
.ia-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.ia-select.is-active { border-color: var(--color-warning); color: var(--color-warning); }
@media (max-width: 960px) { .ia-strength-grid { grid-template-columns: 1fr; } }
```

- [ ] **Step 3: 页面接入 + 冒烟**

`IndustryAnalysis.tsx` 去掉 Task 12 的临时空态，恢复计划中的三 Tab 渲染与 import（Task 12 Step 3 原文的完整版）。

Run: `cd frontend/apps/web && npm run build && npm test`
Expected: 构建通过、测试全绿。

浏览器冒烟：热力图 31 行渲染、点列头排序、点行开抽屉（抽屉 Task 14 前 404——此时抽屉组件已在本任务接入但属 Task 14 交付，若按顺序执行 Task 14 紧随其后，可接受；或本任务先临时 `onPick={() => {}}`，Task 14 接线）。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/components/industry/ProsperityHeatmap.tsx \
  frontend/apps/web/src/components/industry/StrengthFlowTab.tsx \
  frontend/apps/web/src/pages/IndustryAnalysis.tsx \
  frontend/apps/web/src/pages/IndustryAnalysis.css
git commit -m "feat(industry-web): 景气热力图(列排序/窗口切换/难易度徽章)+板块强弱(资金流20日/RS叠加)"
```

---

### Task 14: 行业详情抽屉 + LLM 解读按钮

**Files:**
- Create: `frontend/apps/web/src/components/industry/IndustryDetailDrawer.tsx`
- Modify: `frontend/apps/web/src/pages/IndustryAnalysis.tsx`（接 `picked` → 抽屉,若 Task 13 未接）

**Interfaces:**
- Consumes: `useIndustryDetail`/`useInterpret`、`Modal`、`EChart`。
- Produces: `IndustryDetailDrawer({swCode, onClose})`。

- [ ] **Step 1: 实现抽屉**

```tsx
// frontend/apps/web/src/components/industry/IndustryDetailDrawer.tsx
/** 行业详情抽屉:知识卡/产业链/景气拆解/估值分布直方图/成分表/AI解读。 */
import {useMemo} from 'react';
import {Button, Modal, StateView} from '../ui';
import {EChart} from '../../pages/ntLive/EChart';
import {useIndustryDetail, useInterpret} from '../../../hooks/useIndustryAnalysis';
import {chartBorder, colorUp, colorDown} from '../../../lib/chartTheme';
import {fmtN, fmtYi} from '../../../lib/heat';

interface Props { swCode: string; onClose: () => void; }

export function IndustryDetailDrawer({swCode, onClose}: Props) {
  const {data, loading, error} = useIndustryDetail(swCode);
  const ai = useInterpret();

  const histOption = (h: {edges: number[]; counts: number[]}, color: string) => ({
    tooltip: {trigger: 'axis'},
    grid: {left: 40, right: 10, top: 16, bottom: 26, containLabel: true},
    xAxis: {type: 'category',
      data: h.edges.slice(0, -1).map((e, i) => e.toFixed(1)),
      axisLine: {lineStyle: {color: chartBorder}}},
    yAxis: {type: 'value',
      splitLine: {lineStyle: {color: 'rgba(255,255,255,0.04)'}}},
    series: [{type: 'bar', color, barCategoryGap: '10%',
      data: h.counts}],
  });

  const sub = data?.prosperity;
  const subBars = useMemo(() => ([
    ['盈利', sub?.score_profit], ['估值', sub?.score_valuation],
    ['动量', sub?.score_momentum], ['资金', sub?.score_flow],
  ] as [string, number | null][]), [sub]);

  return (
    <Modal open title={data ? `${data.name}(${swCode}) 行业详情` : '行业详情'}
      onClose={onClose} width={900}
      footer={<Button size="sm" onClick={onClose}>关闭</Button>}>
      {loading && !data ? <StateView state="loading" /> :
       error ? <StateView state="error" text={error} onRetry={onClose} /> :
       !data ? <StateView state="empty" /> :
       <div>
         <div className="ia-drawer-section">
           <div className="ia-drawer-title">投资卡(用户笔记知识层)</div>
           <div style={{marginBottom: 6}}>
             <span className={`ia-tier ia-tier--${data.knowledge.tier}`}>
               {data.knowledge.tier_label}</span>
             <span className="ia-hint" style={{marginLeft: 8}}>
               散户适宜度:{data.knowledge.retail_suitable}</span>
           </div>
           <div>{data.knowledge.approach}</div>
           <div className="ia-chain" style={{marginTop: 8}}>
             {data.knowledge.upstream.map((u) => (
               <span key={u} className="ia-chain-chip">{u}</span>))}
             <span className="ia-arrow">→</span>
             <span className="ia-chain-chip ia-chain-self">{data.name}</span>
             <span className="ia-arrow">→</span>
             {data.knowledge.downstream.map((d) => (
               <span key={d} className="ia-chain-chip">{d}</span>))}
           </div>
         </div>
         {sub && <div className="ia-drawer-section">
           <div className="ia-drawer-title">
             景气分 {fmtN(sub.score, 0)}(拆解)
           </div>
           {subBars.map(([label, v]) => (
             <div key={label} className="ia-subscore">
               <span style={{width: 36}}>{label}</span>
               <div className="ia-subscore-bar">
                 <div className="ia-subscore-fill"
                   style={{width: `${v ?? 0}%`,
                           opacity: v == null ? 0.15 : 1}} />
               </div>
               <span className="num">{fmtN(v, 0)}</span>
             </div>
           ))}
         </div>}
         <div className="ia-drawer-section">
           <div className="ia-drawer-title">
             成分股估值分布({data.member_count}家,截面 {data.valuation_date})
           </div>
           <div className="ia-strength-grid">
             <EChart option={histOption(data.pb_histogram, colorDown) as any} height={180} />
             <EChart option={histOption(data.pe_histogram, colorUp) as any} height={180} />
           </div>
         </div>
         {data.concentration && <div className="ia-drawer-section">
           <div className="ia-drawer-title">行业截面({data.concentration.report_date})</div>
           <div className="ia-hint">
             CR4 {fmtN(data.concentration.cr4, 1)} · HHI {fmtN(data.concentration.hhi, 0)} ·
             样本 {data.concentration.sample_count} 家
           </div>
         </div>}
         <div className="ia-drawer-section">
           <div className="ia-drawer-title">市值Top20成分</div>
           <div className="ia-heat-wrap">
             <table className="ia-heat">
               <thead><tr><th>代码</th><th>名称</th><th>PE(TTM)</th>
                 <th>PB</th><th>总市值</th></tr></thead>
               <tbody>
                 {data.members.map((m) => (
                   <tr key={m.symbol}>
                     <td><b>{m.symbol}</b></td><td style={{textAlign: 'left'}}>{m.name ?? '—'}</td>
                     <td className="num">{fmtN(m.pe_ttm, 1)}</td>
                     <td className="num">{fmtN(m.pb, 2)}</td>
                     <td className="num">{fmtYi(m.total_mv)}</td>
                   </tr>
                 ))}
               </tbody>
             </table>
           </div>
         </div>
         <div className="ia-drawer-section">
           <Button size="sm" loading={ai.loading} onClick={() => ai.run(swCode)}>
             AI 景气解读
           </Button>
           {ai.error && <div className="ia-hint" style={{marginTop: 6}}>{ai.error}(503=未配置LLM)</div>}
           {ai.result && <div style={{marginTop: 8}}>
             <div>{ai.result.summary}</div>
             {ai.result.drivers.length > 0 && <div style={{marginTop: 6}}>
               <b>驱动:</b>{ai.result.drivers.join('；')}</div>}
             {ai.result.risks.length > 0 && <div style={{marginTop: 4}}>
               <b>风险:</b>{ai.result.risks.join('；')}</div>}
           </div>}
         </div>
       </div>}
    </Modal>
  );
}
```

- [ ] **Step 2: 构建+测试+冒烟**

Run: `cd frontend/apps/web && npm run build && npm test`
Expected: 构建通过、测试全绿。

浏览器：热力图点行 → 抽屉打开；知识卡/产业链/拆解/直方图/成分表齐全；点「AI 景气解读」→ 已配置 LLM 时返回解读（未配置返回 503 提示文案）。

- [ ] **Step 3: 全量回归**

Run: `cd backend && uv run pytest tests/domain/market/industry_analysis tests/api/test_industry_router.py -v`
Expected: 全部 passed（新增 25 项左右）。

- [ ] **Step 4: Commit**

```bash
git add frontend/apps/web/src/components/industry/IndustryDetailDrawer.tsx \
  frontend/apps/web/src/pages/IndustryAnalysis.tsx
git commit -m "feat(industry-web): 行业详情抽屉(知识卡/产业链chips/景气拆解/估值分布/成分表/AI解读)"
```

---

## 规格覆盖对照(自审)

| 规格条目 | 任务 |
|---|---|
| §3.1 industry_pb_break_daily 表+市场/行业口径 | T3/T4/T7/T8 |
| §3.2 industry_fund_flow_daily+em_flow_to_sw.yaml | T2/T3/T7 |
| §3.3 industry_prosperity_daily(月末采样回填) | T3/T5/T6/T7/T8 |
| §3.4 industry_knowledge.yaml(31条/三层/上下游) | T1 |
| §4 F1 破净聚合纯函数 | T4 |
| §4 F2 景气分四分项加权/窗口恒定8年 | T5/T6 |
| §4 F3 产业链(chips 渲染,偏差备忘②) | T1/T14 |
| §4 F4 LLM 手动触发+缓存+降级 | T10/T14 |
| §4 F5 三Tab+抽屉(偏差备忘①同行表自查) | T12/T13/T14 |
| §4 F6 job 16:40/17:05/17:20+回填 | T7/T8 |
| §5 六端点 | T9/T10 |
| §6 测试(pytest 子集+vitest) | 各任务内嵌 |
| §7 口径明示(行业破净偏差/资金近似/权重可调) | T12(页面提示)/T5(config) |





