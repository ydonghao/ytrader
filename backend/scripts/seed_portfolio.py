"""
Portfolio Seed
==============
一次性 seed 脚本: 标的池 + 预置组合定义。

幂等: 重复执行覆盖(upsert / 已存在则跳过)。

部署后首次运行:
  cd backend && .venv/bin/python -m scripts.seed_portfolio
"""
import logging
import sys
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from src.infra.database.portfolio.repository import (
    create_portfolio_repository,
)

log = logging.getLogger("seed_portfolio")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ═══════════════════════════════════════════════════════════════
# 标的池: A 股 / H 股 / 美股 三市场, 每类资产各一只
# ═══════════════════════════════════════════════════════════════
INSTRUMENTS = [
    # ── A 股 ──────────────────────────────────────────────────
    {
        "symbol": "sh510300",
        "market": "A",
        "asset_class": "equity",
        "ccy": "CNY",
        "name": "沪深300ETF",
    },
    {
        "symbol": "sh511260",
        "market": "A",
        "asset_class": "bond",
        "ccy": "CNY",
        "name": "10年国债ETF",
    },
    {
        "symbol": "sh518880",
        "market": "A",
        "asset_class": "gold",
        "ccy": "CNY",
        "name": "华安黄金ETF",
    },
    {
        "symbol": "sh511990",
        "market": "A",
        "asset_class": "cash",
        "ccy": "CNY",
        "name": "华宝添益",
    },
    # ── H 股(港股, 纯5位数字) ─────────────────────────────────
    {
        "symbol": "02800",
        "market": "HK",
        "asset_class": "equity",
        "ccy": "HKD",
        "name": "盈富基金(恒生指数)",
    },
    {
        "symbol": "02819",
        "market": "HK",
        "asset_class": "bond",
        "ccy": "HKD",
        "name": "恒生国债指数ETF",
    },
    {
        "symbol": "02840",
        "market": "HK",
        "asset_class": "gold",
        "ccy": "HKD",
        "name": "SPDR金ETF",
    },
    {
        "symbol": "02815",
        "market": "HK",
        "asset_class": "cash",
        "ccy": "HKD",
        "name": "港元货币市场基金",
    },
    # ── 美股 ──────────────────────────────────────────────────
    {
        "symbol": "VOO",
        "market": "US",
        "asset_class": "equity",
        "ccy": "USD",
        "name": "标普500ETF",
    },
    {
        "symbol": "TLT",
        "market": "US",
        "asset_class": "bond",
        "ccy": "USD",
        "name": "20+年国债ETF",
    },
    {
        "symbol": "GLD",
        "market": "US",
        "asset_class": "gold",
        "ccy": "USD",
        "name": "黄金ETF",
    },
    {
        "symbol": "SHV",
        "market": "US",
        "asset_class": "cash",
        "ccy": "USD",
        "name": "短债ETF",
    },
]


# ═══════════════════════════════════════════════════════════════
# 预置组合: 3 个经典策略
# holdings 按资产类配: 每类选一个代表标的, target_weight 为该类权重
# ═══════════════════════════════════════════════════════════════
PRESET_PORTFOLIOS = [
    {
        "name": "永久投资组合",
        "strategy_type": "permanent",
        "rebalance_threshold": 0.05,
        "initial_capital": 100000.0,
        "holdings": [
            # equity 25% (A 股代表)
            ("sh510300", 0.25),
            ("sh511260", 0.25),  # bond 25%
            ("sh518880", 0.25),  # gold 25%
            ("sh511990", 0.25),  # cash 25%
        ],
    },
    {
        "name": "全天候(简化)",
        "strategy_type": "all_weather",
        "rebalance_threshold": 0.05,
        "initial_capital": 100000.0,
        "holdings": [
            ("sh510300", 0.30),  # equity 30%
            ("sh511260", 0.55),  # bond 55%
            ("sh518880", 0.15),  # gold 15%
            # cash 0%
        ],
    },
    {
        "name": "黄金蝴蝶",
        "strategy_type": "golden_butterfly",
        "rebalance_threshold": 0.05,
        "initial_capital": 100000.0,
        "holdings": [
            ("sh510300", 0.40),  # equity 40%
            ("sh511260", 0.20),  # bond 20%
            ("sh518880", 0.20),  # gold 20%
            ("sh511990", 0.20),  # cash 20%
        ],
    },
]


def seed_instruments(repo) -> None:
    """Seed 标的池(幂等 upsert)。"""
    log.info("=== Seed 标的池 ===")
    for inst in INSTRUMENTS:
        result = repo.upsert_instrument(**inst)
        log.info(
            f"  [{inst['symbol']}] {inst['name']} "
            f"({inst['market']}/{inst['asset_class']}) id={result.id}"
        )


def seed_preset_portfolios(repo) -> None:
    """Seed 预置组合(已存在则跳过 holdings, 避免覆盖用户调整)。"""
    log.info("=== Seed 预置组合 ===")
    existing = {p.name for p in repo.list_portfolios(active_only=False)}

    for preset in PRESET_PORTFOLIOS:
        name = preset["name"]
        if name in existing:
            log.info(f"  [{name}] 已存在, 跳过")
            continue

        p = repo.create_portfolio(
            name=name,
            strategy_type=preset["strategy_type"],
            rebalance_threshold=preset["rebalance_threshold"],
            initial_capital=preset["initial_capital"],
        )

        # 构造 holdings: 按真实最近收盘价算 shares, 让初始配置
        # 直接接近目标权重(而非占位价 100 导致偏离)。
        # 无行情数据(标的未同步)时回退占位价 100。
        from datetime import date
        today = date.today()
        holdings = []
        for symbol, weight in preset["holdings"]:
            inst = repo.get_instrument_by_symbol(symbol)
            if not inst:
                log.warning(
                    f"  [{name}] 标的 {symbol} 不在池中, 跳过"
                )
                continue
            price = repo.get_close_price(inst.symbol, today)
            if price and price > 0:
                shares = int(
                    preset["initial_capital"] * weight / price
                )
                cost_price = price
            else:
                shares = int(
                    preset["initial_capital"] * weight / 100.0
                )
                cost_price = 100.0
            holdings.append(
                {
                    "instrument_id": inst.id,
                    "target_weight": weight,
                    "shares": shares,
                    "cost_price": cost_price,
                }
            )
        repo.set_holdings(p.id, holdings)
        log.info(
            f"  [{name}] 创建, id={p.id}, "
            f"{len(holdings)} 持仓"
        )


def main():
    repo = create_portfolio_repository()
    seed_instruments(repo)
    seed_preset_portfolios(repo)
    log.info("=== Seed 完成 ===")


if __name__ == "__main__":
    main()
