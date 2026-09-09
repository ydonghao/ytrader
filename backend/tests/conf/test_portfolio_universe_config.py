from conf.settings import PortfolioUniverseConfig


def test_portfolio_universe_config_parses():
    raw = {
        "bars": [
            {"symbol": "VOO", "market": "US", "ccy": "USD",
             "name": "标普500", "asset": "equity"},
            {"symbol": "sh510300", "market": "A", "ccy": "CNY",
             "name": "沪深300ETF", "asset": "equity"},
        ],
        "fx": [{"pair": "USDCNY"}],
    }
    cfg = PortfolioUniverseConfig(**raw)
    assert len(cfg.bars) == 2
    assert cfg.bars[0].symbol == "VOO"
    assert cfg.bars[0].market == "US"
    assert cfg.bars[1].ccy == "CNY"
    assert cfg.fx[0].pair == "USDCNY"
