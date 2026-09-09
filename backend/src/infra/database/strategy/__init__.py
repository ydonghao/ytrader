"""组合回测结果持久化（infra 层）。

PortfolioBacktestResult: SQLModel 表模型
PortfolioBacktestRepository: 实现 IPortfolioBacktestRepository

通过 SQLModel.metadata.create_all 自动建表（需在 main.py 启动时被 import）。
"""
