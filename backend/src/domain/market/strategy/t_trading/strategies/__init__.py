"""
做T策略注册表
==============
集中管理 4 种做T算法 + 元数据（供前端原理卡片）。
"""
from .base import ParamSpec, TStrategy
from .fixed_band import FixedBandStrategy
from .grid import GridStrategy
from .ma_deviation import MADeviationStrategy
from .martingale import MartingaleStrategy

T_STRATEGY_REGISTRY: dict[str, type[TStrategy]] = {
    "grid": GridStrategy,
    "fixed_band": FixedBandStrategy,
    "ma_deviation": MADeviationStrategy,
    "martingale": MartingaleStrategy,
}


def build_strategy(name: str, params: dict) -> TStrategy:
    """
    根据名字 + 参数构建做T策略实例。

    对 fixed_band：前端传 step_pct(%) / levels / qty，这里合成 steps 列表。
    """
    name = name.lower()
    cls = T_STRATEGY_REGISTRY.get(name)
    if cls is None:
        avail = ", ".join(T_STRATEGY_REGISTRY.keys())
        raise ValueError(f"未知做T算法 '{name}'，可用: {avail}")

    if name == "fixed_band":
        step_pct = float(params.get("step_pct", 1.0)) / 100.0
        levels = int(params.get("levels", 3))
        qty = int(params.get("qty", 200))
        steps = [step_pct * i for i in range(1, levels + 1)]
        return FixedBandStrategy(steps=steps, qty=qty)

    # 其余算法直接透传参数
    kwargs = {}
    for k, v in params.items():
        if hasattr(cls, k) or k in _ACCEPTED_KWARGS.get(name, set()):
            kwargs[k] = v
    return cls(**kwargs)


# 显式允许的构造参数（避免 dataclass 非字段参数报错）
_ACCEPTED_KWARGS: dict[str, set[str]] = {
    "grid": {"band_pct", "grids", "qty_per_grid"},
    "ma_deviation": {"ma_period", "dev_threshold", "qty"},
    "martingale": {
        "drop_step", "multiplier", "take_profit", "base_qty", "max_levels",
    },
    "fixed_band": set(),
}


def algorithm_metas() -> list[dict]:
    """返回所有算法的元数据（前端原理卡片用）。不实例化依赖参数的字段。"""
    out: list[dict] = []
    for name, cls in T_STRATEGY_REGISTRY.items():
        # 用默认参数实例化以读取 meta（display_name/原理/参数规格等）
        inst = _default_instance(cls)
        meta = inst.meta()
        meta["name"] = name
        out.append(meta)
    return out


def _default_instance(cls: type[TStrategy]) -> TStrategy:
    """用默认值实例化（兼容 dataclass 默认参数）"""
    try:
        return cls()
    except TypeError:
        # fixed_band steps 默认已给，理论不会到这；兜底
        return cls(**{})  # noqa


__all__ = [
    "T_STRATEGY_REGISTRY",
    "build_strategy",
    "algorithm_metas",
    "TStrategy",
    "ParamSpec",
    "GridStrategy",
    "FixedBandStrategy",
    "MADeviationStrategy",
    "MartingaleStrategy",
]
