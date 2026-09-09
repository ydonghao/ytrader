"""
Market Data Tools
=================
Tools for retrieving market data using existing providers.
"""
from typing import Any

from ..sync.sync_provider import SyncProvider, OHLCVBar


class MarketDataTools:
    """
    Tools for accessing market data.
    
    Provides unified interface to stock data from various providers.
    """
    
    def __init__(self, provider: SyncProvider | None = None) -> None:
        """
        Initialize with optional data provider.
        
        Args:
            provider: SyncProvider instance (e.g., SinaProvider)
        """
        self.provider = provider
    
    def get_stock_data(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
        interval: str = "1d",
        datalen: int = 1300,
    ) -> list[dict[str, Any]]:
        """
        Get stock price data as list of dicts.
        
        Args:
            symbol: Stock symbol (e.g., 'sh600000')
            start_date: Start date YYYY-MM-DD
            end_date: End date YYYY-MM-DD
            interval: Data interval ('1d', '5m', '15m', '60m')
            datalen: Number of bars to retrieve
            
        Returns:
            List of dicts with OHLCV data
        """
        if self.provider is None:
            return []
        
        try:
            if interval == "1d":
                bars = self.provider.fetch_daily(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    datalen=datalen,
                )
            else:
                bars = self.provider.fetch_minute(
                    symbol=symbol,
                    interval=interval,
                    datalen=datalen,
                )
            
            return [self._bar_to_dict(bar) for bar in bars]
        except Exception:
            return []
    
    def _bar_to_dict(self, bar: OHLCVBar) -> dict[str, Any]:
        """Convert OHLCVBar to dictionary."""
        return {
            "symbol": bar.symbol,
            "trade_time": bar.trade_time.isoformat(),
            "open": bar.open_,
            "high": bar.high_,
            "low": bar.low_,
            "close": bar.close_,
            "volume": bar.volume,
            "amount": bar.amount,
            "interval": bar.interval,
            "market": bar.market,
            "provider": bar.provider,
        }
    
    def get_stock_list(self, market: str = "A") -> list[str]:
        """
        Get list of stock symbols.
        
        Args:
            market: Market code ('A', 'HK')
            
        Returns:
            List of stock symbols
        """
        if self.provider is None:
            return []
        
        try:
            return self.provider.get_stock_list(market=market)
        except Exception:
            return []


def get_stock_data(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "1d",
    datalen: int = 1300,
    provider: SyncProvider | None = None,
) -> list[dict[str, Any]]:
    """
    Standalone function to get stock data.
    
    Args:
        symbol: Stock symbol
        start_date: Start date
        end_date: End date
        interval: Data interval
        datalen: Number of bars
        provider: Optional data provider
        
    Returns:
        List of dicts with OHLCV data
    """
    tools = MarketDataTools(provider=provider)
    return tools.get_stock_data(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        interval=interval,
        datalen=datalen,
    )
