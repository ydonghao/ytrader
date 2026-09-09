# 多 Agent 交易决策系统 (Multi-Agent Trading)

**项目**: YTrader 量化交易平台
**模块**: Multi-Agent Trading System
**版本**: 1.0
**日期**: 2026-03-31
**状态**: 草稿

---

## 一、模块概述

多 Agent 交易决策系统模拟真实交易公司的运作模式，部署多个专业化的 LLM-powered Agent 以协作方式评估市场状况并形成交易决策。

核心设计原则：
- **专业化分工**：每个 Agent 专注于特定分析领域
- **辩论机制**：多空双方充分辩论，避免单一视角偏差
- **风险管理前置**：风控 Agent 对最终决策进行独立审查
- **人类参与**：用户可随时插话、提问、确认决策

---

## 二、Agent 架构

### 2.1 Agent 层级

```
┌─────────────────────────────────────────────────────────┐
│                    Trader (交易员)                       │
│         合成分析师/研究员报告 → 做出 BUY/HOLD/SELL 决策    │
└─────────────────────────┬───────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌─────────────────┐ ┌───────────┐ ┌─────────────────────┐
│  Bull Researcher │ │ Bear Res. │ │ Risk Management Team │
│   (看多研究员)   │ │ (看空)    │ │ (风控团队)            │
└────────┬────────┘ └─────┬─────┘ └──────────┬────────────┘
         │                │                  │
         └────────┬────────┴──────────────────┘
                  ▼
         Research Manager (研究经理)
           主持多空辩论 → 形成投资建议
                  │
┌────────┬───────┬┴───────┬──────────┐
▼        ▼       ▼        ▼          ▼
Market  Social  News  Fundamentals  China
Analyst Analyst Analyst   Analyst   Market
(技术)  (情感)  (新闻)   (基本面)   (国情)
```

### 2.2 Analyst Team (分析师团队)

| Agent | 职责 | 工具/数据 |
|-------|------|----------|
| `MarketAnalyst` | 技术分析 (MA, MACD, RSI, Bollinger, ATR, VWAP) | K线数据、技术指标 |
| `SocialMediaAnalyst` | 社交媒体情绪 | 社区讨论、论坛舆情 |
| `NewsAnalyst` | 新闻事件、宏观指标 | 新闻聚合数据 |
| `FundamentalsAnalyst` | 财报、估值、现金流 | 财务数据、基本面数据 |
| `ChinaMarketAnalyst` | A股特殊规则 (涨跌停、T+1、融资融券) | A股特有数据 |

### 2.3 Researcher Team (研究员团队)

| Agent | 职责 | 辩论策略 |
|-------|------|----------|
| `BullResearcher` | 看多方倡导者，论证投资价值 | 强调增长潜力、竞争优势、正面指标 |
| `BearResearcher` | 空方倡导者，揭示风险因素 | 批评看多论点、分析利空、强调不确定性 |

### 2.4 Risk Management Team (风控团队)

| Agent | 职责 | 关注点 |
|-------|------|------|
| `AggressiveDebater` | 激进方，主张承担风险获取收益 | 仓位大小、杠杆、机会成本 |
| `ConservativeDebater` | 保守方，主张降低风险 | 回撤控制、波动率、清盘线 |
| `NeutralDebater` | 中立方，平衡双方观点 | 风险收益比、最优仓位 |

---

## 三、LangGraph 工作流

### 3.1 状态定义

```python
class AgentState(MessagesState):
    # 上下文
    company_of_interest: str
    trade_date: str
    market: str  # A股/港股/美股

    # 分析师报告
    market_report: str | None
    sentiment_report: str | None
    news_report: str | None
    fundamentals_report: str | None
    china_market_report: str | None

    # 辩论状态
    investment_debate_state: InvestDebateState
    risk_debate_state: RiskDebateState

    # 最终决策
    final_trade_decision: str | None  # BUY / HOLD / SELL
    decision_confidence: float | None
```

```python
class InvestDebateState(TypedDict):
    bull_arguments: list[str]
    bear_arguments: list[str]
    current_round: int
    max_rounds: int
    investment_recommendation: str | None


class RiskDebateState(TypedDict):
    risky_position: str
    conservative_position: str
    neutral_position: str
    risk_approved: bool
    risk_conditions: list[str]
```

### 3.2 图结构

```
START
   │
   ▼
[Analyst Nodes] (并行)
   │
   ▼
Bull/Bear Debate Loop ──→ Research Manager
   │                           │
   │ ←── max_rounds 循环 ──────┘
   │
   ▼
Trader Decision (BUY/HOLD/SELL)
   │
   ▼
Risk Debate Loop (Aggressive → Conservative → Neutral → Risk Judge)
   │
   ▼
Risk Approval / Rejection
   │
   ▼
END
```

### 3.3 条件路由

```python
# 分析师节点完成后的路由
def should_continue_analyst(analyst_name: str) -> str:
    """检查分析师是否需要调用工具获取更多数据"""
    return "call_tools" if needs_more_data else "end"

# 多空辩论路由
def should_continue_debate(state: AgentState) -> str:
    """辩论轮次未满则继续，否则输出投资建议"""
    return "continue" if state["investment_debate_state"]["current_round"] < state["investment_debate_state"]["max_rounds"] else "end"

# 风控辩论路由
def should_continue_risk_analysis(state: AgentState) -> str:
    """风控讨论轮次：Aggressive → Conservative → Neutral → Risk Judge"""
    round_num = state["risk_debate_state"]["current_round"]
    if round_num == 0:
        return "aggressive"
    elif round_num == 1:
        return "conservative"
    elif round_num == 2:
        return "neutral"
    else:
        return "judge"
```

---

## 四、记忆系统

### 4.1 ChromaDB 向量记忆

每次决策后将当前市场情境和结果存入向量数据库，供后续相似情境参考：

```python
class FinancialSituationMemory:
    def __init__(self):
        self.collection = chroma_client.get_or_create_collection(
            "financial_situations"
        )
        self.embedding_model = "text-embedding-3-small"

    def add_situation(
        self,
        context: dict,
        decision: str,
        outcome: str,  # BUY/HOLD/SELL + 事后收益
        sentiment_summary: str
    ) -> None:
        """存储决策情境"""
        embedding = self.embed(context)
        self.collection.add(
            ids=[str(uuid.uuid4())],
            embeddings=[embedding],
            documents=[json.dumps({
                "context": context,
                "decision": decision,
                "outcome": outcome,
                "sentiment_summary": sentiment_summary,
                "timestamp": datetime.now().isoformat()
            })]
        )

    def get_similar_situations(self, current_context: dict, k: int = 2) -> list[dict]:
        """获取最相似的历史情境"""
        embedding = self.embed(current_context)
        results = self.collection.query(
            query_embeddings=[embedding],
            n_results=k
        )
        return [json.loads(doc) for doc in results["documents"]]
```

### 4.2 记忆检索

研究员 Agent 在辩论前检索相似历史情境：

```python
async def get_past_memories(context: dict) -> str:
    memories = memory.get_similar_situations(context, k=2)
    if not memories:
        return "无相似历史情境"
    return "\n".join([
        f"- 情境{i+1}: 决策={m['decision']}, 结果={m['outcome']}, 摘要={m['sentiment_summary']}"
        for i, m in enumerate(memories)
    ])
```

---

## 五、Prompt 工程

### 5.1 Bull Researcher Prompt

```
你是一位看多的分析师，负责论证投资特定股票的合理性。

你的职责：
1. 分析市场报告、技术指标
2. 从增长潜力、竞争优势、正面指标等角度提出看多论点
3. 反驳空方观点
4. 最终给出投资建议

看多论点应涵盖：
- 增长潜力（市场空间、营收增长）
- 竞争优势（护城河、市场份额）
- 正面指标（技术突破、订单增加）
- 估值吸引力（相对历史/行业）

当前讨论历史：[history]
当前空方论点：[bear_arguments]

请结合上述信息，形成有力的看多论述。
```

### 5.2 Trader Prompt

```
你是一位经验丰富的交易员，负责综合多位分析师的研究报告，做出最终的交易决策。

可用的分析师报告：
- 技术分析：{market_report}
- 情感分析：{sentiment_report}
- 新闻分析：{news_report}
- 基本面分析：{fundamentals_report}

研究经理的投资建议：{investment_recommendation}

你的决策：
- BUY：明确买入信号
- HOLD：观望，不操作
- SELL：明确卖出信号

请给出你的决策，并说明决策理由和信心指数（0-1）。
```

---

## 六、人类参与机制

### 6.1 插话时机

| 时机 | 触发条件 | 动作 |
|------|---------|------|
| 分析师报告后 | 用户主动询问 | 暂停辩论，用户提问 |
| 多空辩论中 | 用户举手 | 插入用户观点 |
| 交易员决策前 | 用户确认 | 用户修改或推翻决策 |
| 风控审核中 | 用户干预 | 用户强制通过或拒绝 |

### 6.2 实现方式

通过 WebSocket 实时流式输出 Agent 讨论过程，用户可随时通过同一 WebSocket 发送干预消息：

```python
class HumanIntervention:
    async def on_user_input(
        self,
        session_id: str,
        message: str,
        interrupt_point: str  # "analyst", "debate", "trader", "risk"
    ) -> None:
        # 暂停当前 Agent
        self.pause_agent(session_id)

        # 记录用户输入
        self.store_user_input(session_id, message, interrupt_point)

        # 通知用户已暂停
        await self.broadcast_status(session_id, "paused_for_human_input")
```

---

## 七、API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `POST /ailab/discuss` | POST | 发起讨论（传入标的、持仓信息） |
| `GET /ailab/discuss/{id}` | GET | 获取讨论状态和历史 |
| `WebSocket /ailab/ws/{discuss_id}` | WS | 实时讨论流（Agent 输出 + 用户输入） |
| `POST /ailab/intervene` | POST | 用户干预（插话/修改决策） |
| `GET /ailab/memory` | GET | 查看历史决策记忆 |
| `POST /ailab/memory/clear` | POST | 清除记忆（重新开始） |

---

## 八、核心组件

| 组件 | 职责 |
|------|------|
| `TradingGraph` | LangGraph 图定义和工作流编排 |
| `AnalystAgent` | 各分析师 Agent 的 Prompt 和工具绑定 |
| `ResearcherDebate` | 多空辩论状态管理和轮次控制 |
| `RiskDebate` | 风控辩论状态管理 |
| `TraderDecision` | 交易员决策合成 |
| `MemoryManager` | ChromaDB 向量记忆的存取 |
| `StreamHandler` | WebSocket 流式输出和用户输入处理 |

---

**文档版本**: 1.0
**最后更新**: 2026-03-31
