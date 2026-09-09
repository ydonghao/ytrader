# 量化策略引擎

## 架构

```
src/domain/market/strategy/
├── signals.py          ← Signal / Position / Trade 数据模型
├── base.py             ← Strategy ABC
├── indicators.py       ← SMA / EMA / MACD / RSI / ATR / 布林带
├── backtester.py       ← 回测引擎
├── optimizer.py        ← 网格搜索参数优化
├── backtest_cli.py     ← CLI 入口
└── strategies/
    ├── __init__.py     ← STRATEGY_REGISTRY + get_strategy()
    ├── sma_cross.py    ← SMA 金叉/死叉
    ├── rsi.py          ← RSI 超买超卖
    ├── macd.py         ← MACD
    └── bollinger.py    ← 布林带
```

## 快速开始

```bash
# 单标的回测
cd backend
python -m src.domain.market.strategy.backtest_cli \
    --strategy sma_cross \
    --symbols sh600000 \
    --start 2023-01-01 --end 2025-12-31 \
    --param fast_period=5 --param slow_period=20

# 多标的回测
python -m src.domain.market.strategy.backtest_cli \
    --strategy rsi \
    --symbols sh600000,sh600519,sh600036 \
    --start 2023-01-01 --end 2025-12-31 \
    --param period=14 --param overbought=70 --param oversold=30

# 输出结果
python -m src.domain.market.strategy.backtest_cli \
    --strategy bollinger \
    --symbols sh600000 \
    --start 2024-01-01 --end 2025-12-31 \
    --initial-capital 500000
```

输出示例：
```
=== SMA_Cross Backtest Results ===
标的:   sh600000
回测期: 2023-01-01 → 2025-12-31
初始资金: 1,000,000.00
最终权益: 1,116,197.21
收益率:   11.6%
夏普率:   0.45
最大回撤: 20.5%
胜率:     40.0%
盈亏比:   2.35
总交易数: 43
```

## 内置策略

| 策略 | 参数 | 说明 |
|------|------|------|
| `sma_cross` | `fast_period`, `slow_period` | SMA 金叉买入，死叉卖出 |
| `rsi` | `period`, `overbought`, `oversold` | RSI 超买超卖区域反转 |
| `macd` | `fast`, `slow`, `signal` | MACD 金叉死叉 |
| `bollinger` | `period`, `std_dev` | 布林带价格触及轨道反转 |

## 回测引擎参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--initial-capital` | 1,000,000 | 初始资金 |
| `--commission` | 0.0003 | 手续费率（0.03%） |
| `--slippage` | 0.0001 | 滑点（0.01%） |

## 策略编写

```python
from src.domain.market.strategy.base import SingleSymbolStrategy
from src.domain.market.strategy.signals import Action, Signal
from src.domain.market.strategy.indicators import sma
from src.domain.market.sync.sync_provider import OHLCVBar

class MyStrategy(SingleSymbolStrategy):
    name = "MyStrategy"
    
    def __init__(self, fast=5, slow=20):
        self.fast = fast
        self.slow = slow
    
    def generate_signals_for_symbol(self, symbol, bars):
        closes = [b.close_ for b in bars]
        fast_sma = sma(closes, self.fast)
        slow_sma = sma(closes, self.slow)
        signals = []
        for i in range(1, len(bars)):
            if (fast_sma[i-1] <= slow_sma[i-1] and 
                fast_sma[i] > slow_sma[i]):
                signals.append(Signal(
                    symbol=symbol,
                    action=Action.BUY,
                    price=bars[i].close_,
                    timestamp=bars[i].trade_time,
                ))
        return signals
```

## 重要提示

**多标的回测的仓位管理**：回测引擎使用"全仓再投资"模式（每次用 95% 可用资金开仓）。这会随资金增长自动增大仓位，导致：
- 多标的组合时资金快速复利
- 最大回撤可能接近 100%（极端行情下）

实盘使用前，请根据风险管理需求调整 `position_size` 参数。

## 测试

```bash
cd backend
PYTHONPATH=src .venv/bin/pytest tests/strategy/ -v
```
