"""
Fundamentals Tool
=================
Tool for retrieving fundamental company data.
"""
from typing import Any

try:
    import akshare as ak
    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False


class FundamentalsTools:
    """
    Tools for accessing fundamental company data.
    
    Uses akshare to retrieve financial statements, valuation metrics, etc.
    """
    
    def __init__(self) -> None:
        """Initialize fundamentals tools."""
        self._available = _AKSHARE_AVAILABLE
    
    def get_stock_info(self, symbol: str) -> dict[str, Any]:
        """
        Get basic stock information.
        
        Args:
            symbol: Stock symbol (e.g., '600000' for Shanghai, '000001' for Shenzhen)
            
        Returns:
            Dict with stock info
        """
        if not self._available:
            return {}
        
        try:
            # Convert to akshare format
            if symbol.startswith("sh"):
                code = symbol[2:]
                market = "sh"
            elif symbol.startswith("sz"):
                code = symbol[2:]
                market = "sz"
            else:
                code = symbol
                market = ""
            
            info = ak.stock_individual_info_em(symbol=code)
            result = {}
            for _, row in info.iterrows():
                result[row["item"]] = row["value"]
            return result
        except Exception:
            return {}
    
    def get_financial_statement(self, symbol: str) -> dict[str, Any]:
        """
        Get financial statement data.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dict with financial statement data
        """
        if not self._available:
            return {}
        
        try:
            if symbol.startswith("sh"):
                code = symbol[2:]
            elif symbol.startswith("sz"):
                code = symbol[2:]
            else:
                code = symbol
            
            # Get income statement
            income = ak.stock_zyjs_em(symbol=code)
            return {"income_statement": income.to_dict()}
        except Exception:
            return {}
    
    def get_valuation(self, symbol: str) -> dict[str, Any]:
        """
        Get valuation metrics.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Dict with valuation metrics
        """
        if not self._available:
            return {}
        
        try:
            if symbol.startswith("sh"):
                code = symbol[2:]
            elif symbol.startswith("sz"):
                code = symbol[2:]
            else:
                code = symbol
            
            # Get P/E ratio and other metrics
            df = ak.stock_a_indicator_lg(symbol=code)
            if not df.empty:
                latest = df.iloc[-1].to_dict()
                return latest
            return {}
        except Exception:
            return {}


def get_fundamentals(symbol: str) -> dict[str, Any]:
    """
    Standalone function to get fundamental data.
    
    Args:
        symbol: Stock symbol
        
    Returns:
        Dict with fundamental data
    """
    tools = FundamentalsTools()
    
    info = tools.get_stock_info(symbol)
    valuation = tools.get_valuation(symbol)
    
    return {
        "stock_info": info,
        "valuation": valuation,
    }


def format_fundamentals_for_prompt(data: dict[str, Any]) -> str:
    """
    Format fundamentals data into readable string for LLM.
    
    Args:
        data: Fundamentals data dict
        
    Returns:
        Formatted string
    """
    lines = ["=== Company Fundamentals ==="]
    
    if "stock_info" in data:
        lines.append("\n--- Stock Info ---")
        for key, value in data["stock_info"].items():
            lines.append(f"{key}: {value}")
    
    if "valuation" in data:
        lines.append("\n--- Valuation Metrics ---")
        val = data["valuation"]
        # Select most important metrics
        important = ["市盈率(动态)", "市净率", "总市值", "流通市值", "每股收益", "每股净资产"]
        for key in important:
            if key in val:
                lines.append(f"{key}: {val[key]}")
    
    return "\n".join(lines)
