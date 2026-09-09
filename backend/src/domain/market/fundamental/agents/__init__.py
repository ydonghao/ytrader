"""个股基本面深度分析 Agent（P1）。

复用 src/domain/market/intel/agents/base.py 的 @agent_node 范式
（Jinja2 prompt + 结构化 Pydantic 输出 + tracing/cancel），但消费
stock_financial_detail 真实三大报表数据做定性分析。

本模块独立实现。
"""
