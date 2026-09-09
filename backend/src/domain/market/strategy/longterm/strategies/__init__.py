"""
长期投资组合策略
================
集中管理经典长期投资算法 + 元数据（供前端原理卡片）。

策略门派分布：
  - 动量/趋势: dual_momentum, sma_trend
  - 资产配置:  all_weather
  - 定投:      value_averaging
  - 价值:      magic_formula, fscore_value, dividend（需基本面数据）
"""
from .all_weather import AllWeatherStrategy
from .dual_momentum import DualMomentumStrategy
from .sma_trend import SMATrendStrategy
from .value_averaging import ValueAveragingStrategy

# 价值类策略 import 容错：它们的 DB 表可能未建，import 时不依赖 DB
try:
    from .dividend import DividendStrategy
    from .fscore_value import FScoreValueStrategy
    from .magic_formula import MagicFormulaStrategy
    _HAS_VALUE = True
except Exception:  # pragma: no cover
    _HAS_VALUE = False

# 优化类策略（风险平价/最小方差/MVO/等权）import 容错：依赖 scipy，缺失时跳过
try:
    from ...optimization.equal_weight import EqualWeightStrategy
    from ...optimization.min_variance import MinVarianceStrategy
    from ...optimization.mvo import MVOStrategy
    from ...optimization.risk_parity import RiskParityStrategy
    _HAS_OPTIMIZATION = True
except Exception:  # pragma: no cover
    _HAS_OPTIMIZATION = False


LONGTERM_STRATEGY_REGISTRY: dict[str, type] = {
    "dual_momentum": DualMomentumStrategy,
    "sma_trend": SMATrendStrategy,
    "all_weather": AllWeatherStrategy,
    "value_averaging": ValueAveragingStrategy,
}
if _HAS_VALUE:
    LONGTERM_STRATEGY_REGISTRY["magic_formula"] = MagicFormulaStrategy
    LONGTERM_STRATEGY_REGISTRY["fscore_value"] = FScoreValueStrategy
    LONGTERM_STRATEGY_REGISTRY["dividend"] = DividendStrategy
if _HAS_OPTIMIZATION:
    LONGTERM_STRATEGY_REGISTRY["risk_parity"] = RiskParityStrategy
    LONGTERM_STRATEGY_REGISTRY["min_variance"] = MinVarianceStrategy
    LONGTERM_STRATEGY_REGISTRY["mvo"] = MVOStrategy
    LONGTERM_STRATEGY_REGISTRY["equal_weight"] = EqualWeightStrategy


def build_strategy(name: str, params: dict) -> "object":
    """根据名字 + 参数构建长期策略实例。"""
    name = name.lower()
    cls = LONGTERM_STRATEGY_REGISTRY.get(name)
    if cls is None:
        avail = ", ".join(LONGTERM_STRATEGY_REGISTRY.keys())
        raise ValueError(f"未知长期策略 '{name}'，可用: {avail}")
    kwargs = {}
    for k, v in (params or {}).items():
        kwargs[k] = v
    return cls(**kwargs)


def algorithm_metas() -> list[dict]:
    """返回所有长期策略的元数据（前端原理卡片用）。"""
    out: list[dict] = []
    for name, cls in LONGTERM_STRATEGY_REGISTRY.items():
        try:
            inst = cls()
            meta = inst.meta()
            meta["name"] = name
            out.append(meta)
        except Exception:  # pragma: no cover
            continue
    return out


__all__ = [
    "LONGTERM_STRATEGY_REGISTRY",
    "build_strategy",
    "algorithm_metas",
    "DualMomentumStrategy",
    "SMATrendStrategy",
    "AllWeatherStrategy",
    "ValueAveragingStrategy",
]
