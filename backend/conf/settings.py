import os
import yaml
from pathlib import Path

# backend 根目录（conf/ 的上一级）。所有默认配置路径都以它为基准解析，
# 这样无论从哪个 cwd import conf（uvicorn / 调试脚本 / 定时任务）都能定位到配置。
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = str(_BACKEND_ROOT / "conf" / "config.yaml")
from pydantic import BaseModel
from typing import Optional
from collections.abc import Mapping
from loguru import logger


# ======== Pydantic 配置模型 ========
class ServerConfig(BaseModel):
    host: str
    port: int

class DatabaseConfig(BaseModel):
    """数据库配置"""
    url: str
    pool_size: int = 5
    max_overflow: int = 10
    echo: bool = False


class LoggingConfig(BaseModel):
    level: str
    format: str
    datefmt: str
    rotation: str
    retention: str
    serialize: bool

class IntelRSSSourceConfig(BaseModel):
    name: str
    url: str
    language: str = "en"
    channel: str = ""  # CCTV-specific: domestic/world/finance/tech

class IntelAPIFinnHubConfig(BaseModel):
    enabled: bool = True

class IntelAPINewsnowConfig(BaseModel):
    enabled: bool = True
    base_url: str = "http://localhost:4444/api/s"
    platforms: list[str] = []

class IntelAPIMinifluxConfig(BaseModel):
    enabled: bool = True
    base_url: str = "http://localhost:8380"
    username: str = "admin"
    password: str = "admin123"
    categories: dict[str, int] = {}
    cctv_channel_map: dict[str, str] = {}

class IntelAPIConfig(BaseModel):
    finnhub: Optional[IntelAPIFinnHubConfig] = None
    newsnow: Optional[IntelAPINewsnowConfig] = None
    miniflux: Optional[IntelAPIMinifluxConfig] = None

class IntelAIProcessingConfig(BaseModel):
    enabled: bool = True
    batch_size: int = 20

class SubscriptionWeweRssConfig(BaseModel):
    enabled: bool = True
    base_url: str = "http://localhost:4000"
    category: str = "future_tech"

class SubscriptionConfig(BaseModel):
    rsshub_base: str = "http://localhost:1200"
    wewe_rss_base: str = "http://localhost:4000"
    sync_interval_minutes: int = 15
    wewe_rss: Optional[SubscriptionWeweRssConfig] = None

class IntelConfig(BaseModel):
    rss: Optional[dict[str, list[IntelRSSSourceConfig]]] = None
    api: Optional[IntelAPIConfig] = None
    ai_processing: Optional[IntelAIProcessingConfig] = None
    subscription: Optional[SubscriptionConfig] = None

class LLMSettings(BaseModel):
    encryption_key: str = ""

class PortfolioUniverseBarConfig(BaseModel):
    """配置组合中的行情标的"""
    symbol: str
    market: str        # "A" | "US"
    ccy: str           # "CNY" | "USD"
    name: str
    asset: str         # equity | bond | gold | cash


class PortfolioUniverseFxConfig(BaseModel):
    """配置组合涉及的汇率对"""
    pair: str          # "USDCNY"


class PortfolioUniverseConfig(BaseModel):
    """配置组合标的清单（永久投资组合风格）"""
    bars: list[PortfolioUniverseBarConfig] = []
    fx: list[PortfolioUniverseFxConfig] = []


class QuantUniverseHkEtfConfig(BaseModel):
    """港股 ETF 清单项（akshare 无专用列表，curated）"""
    symbol: str
    name: str = ""


class QuantUniverseIndexConfig(BaseModel):
    """A 股指数清单项（akshare stock_zh_index_daily_em，curated）"""
    symbol: str
    name: str = ""


class QuantUniverseIndexConstituentConfig(BaseModel):
    """宽基指数成分股清单项（akshare index_stock_cons_weight_csindex）"""
    code: str        # 纯6位指数代码（000300），csindex 参数与聚合表 scope_code
    symbol: str      # 带前缀代码（sh000300），对齐 indices 清单
    name: str = ""


class QuantUniverseConfig(BaseModel):
    """量化数据全量同步清单（full_sync / quant_daily 使用）"""
    daily_years: int = 10
    minute_years: int = 2
    commodity_years: int = 3
    minute_intervals: list[str] = ["5m", "15m", "30m", "60m"]
    commodities: dict[str, list[str]] = {}      # {"metals": [...], "energy": [...]}
    fx_pairs: list[str] = []
    hk_etf_symbols: list[QuantUniverseHkEtfConfig] = []
    indices: list[QuantUniverseIndexConfig] = []  # A 股核心指数（stock_zh_index_daily）
    sw_industries: list[QuantUniverseIndexConfig] = []  # 申万一级行业指数（index_hist_sw）
    index_constituents: list[QuantUniverseIndexConstituentConfig] = []  # 宽基成分股（csindex）


class MacroIndicatorConfig(BaseModel):
    """单个宏观经济指标清单项（code 对应 AkshareProvider._MACRO_EXTRACTORS）。"""
    code: str                                   # cn_cpi_yoy / us_ism_pmi ...
    name: str = ""                              # 展示名称（CPI同比）
    unit: str = ""                              # % / 亿元 / ""
    freq: str = "month"                         # month / day / quarter
    category: str = "cn"                        # cn / us / global
    group: str = ""                             # growth / inflation / employment / monetary（经济维度分组，前端按板块聚合）
    provider: str = "akshare"                   # akshare / fred（sync 数据源分发；与展示用 source 区分）
    threshold_high: Optional[float] = None      # 阈值上线（如 PMI 50 荣枯线）
    threshold_low: Optional[float] = None
    direction: str = "neutral"                  # high_good / low_good / neutral
    description: str = ""                       # 简短说明（卡片副标题）
    explanation: str = ""                       # 详细含义解释（tip 弹层）
    doc_url: str = ""                           # 外链：权威资料/百科（tip 中"了解更多"）
    range_low: Optional[float] = None           # 图示区间下限（迷你折线图 Y 轴）
    range_high: Optional[float] = None          # 图示区间上限
    reference_lines: list = []                  # 带语义分界线 [{value, label, severity}]
    source: str = "akshare"                     # 数据源名称
    source_url: str = ""                        # 数据源权威页面（供用户溯源）


class MacroPredictTargetConfig(BaseModel):
    """宏观判断快照的预测标的项（第二层·资产方向含义）。"""
    symbol: str                                 # sh000300 / US.INX / USDCNY / XAU
    name: str = ""                              # 沪深300 / 标普500 / 美元 / 黄金
    asset_class: str = "index"                  # index / fx / commodity


class MacroEvent(BaseModel):
    """中国重大经济事件（图表标注用，静态配置）。"""
    date: str            # "2008-09-15"（ISO 日期）
    title: str           # "雷曼破产·全球金融危机"
    desc: str = ""       # 详细说明


class MacroUniverseConfig(BaseModel):
    """宏观板块数据 + 判断清单（macro_sync / macro_view 使用）。"""
    indicators: list[MacroIndicatorConfig] = []
    global_indices: list[QuantUniverseIndexConfig] = []  # 全球指数（US.DJI / HK.HSI …）
    predict_targets: list[MacroPredictTargetConfig] = []  # 资产方向预测标的
    snapshot_horizon_days: int = 63              # 验证窗口（≈1 季度交易日）
    macro_events: list[MacroEvent] = []           # 历史事件标注（图表标注用）


class DividendValueFiltersConfig(BaseModel):
    """dividend_value 模式默认门槛。"""
    dy_min: float = 3.0
    pb_max: float = 3.0
    pe_min: float = 0.0
    pe_max: float = 60.0
    roe_min: float = 8.0
    debt_max: float = 70.0
    value_metric: str = "pb"        # pb | pe_ttm | pb_pe
    value_window: str = "10y"       # 10y | 20y


class DividendValueConfig(BaseModel):
    """红利低估值选股配置。"""
    exclude_ranges: list[list[str]] = []  # [["2015-06-15","2015-12-31"]]
    filters_default: DividendValueFiltersConfig = DividendValueFiltersConfig()


class ScreenerConfig(BaseModel):
    """选股器配置。"""
    dividend_value: DividendValueConfig = DividendValueConfig()


class BoomRadarConfig(BaseModel):
    """财报季景气雷达(boom)配置"""
    enabled: bool = True
    min_change_pct: float = 50.0      # 业绩大增阈值 %
    news_days_back: int = 7           # 候选股新闻同步回看天数
    llm_daily_limit: int = 30         # 每日 LLM 深读上限(二期用)


class AppConfig(BaseModel):
    server: ServerConfig
    database: DatabaseConfig
    root_path: Optional[str] = ""
    logging: LoggingConfig
    intel: Optional[IntelConfig] = None
    llm: LLMSettings = LLMSettings()
    portfolio_universe: PortfolioUniverseConfig = PortfolioUniverseConfig()
    quant_universe: QuantUniverseConfig = QuantUniverseConfig()
    macro_universe: MacroUniverseConfig = MacroUniverseConfig()
    screener: ScreenerConfig = ScreenerConfig()
    boom_radar: BoomRadarConfig = BoomRadarConfig()


# ======== 配置加载工具 ========
def load_local_config(path=_DEFAULT_CONFIG_PATH) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def deep_merge(dict1: dict, dict2: dict) -> dict:
    """递归合并 dict，dict2 优先"""
    result = dict1.copy()
    for k, v in dict2.items():
        if (
            k in result
            and isinstance(result[k], Mapping)
            and isinstance(v, Mapping)
        ):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    # dict2中有dict1没有的key也会被加入result
    for k in dict2:
        if k not in result:
            result[k] = dict2[k]
    return result


# ======== 配置中心单例 ========
class ConfigCenter:
    """配置中心单例
    ```python
    from conf.settings import ConfigCenter

    class UserService:
        def __init__(self):
            pass

        def do_something(self):
            db_url = ConfigCenter().get().database.url  # 实时取
            print(f"当前数据库URL: {db_url}")
    ```

    Raises:
        RuntimeError: 如果配置未加载

    Returns:
        _type_: _description_
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._config: AppConfig = None
            self._initialized = True

    def load(self, path=_DEFAULT_CONFIG_PATH) -> AppConfig:
        local_conf = load_local_config(path)
        # 本地敏感配置覆盖：conf/config.local.yaml（已 gitignore，不入仓库），
        # 用于在仓库模板 config.yaml 脱敏的情况下保留本地真实密码/密钥。
        local_override = Path(path).parent / "config.local.yaml"
        if local_override.exists():
            local_conf = deep_merge(
                local_conf, load_local_config(str(local_override))
            )
        self._config = AppConfig(**local_conf)
        return self._config

    def get(self):
        if self._instance is None or self._instance._config is None:
            raise RuntimeError("Config not loaded yet. Call load() first.")
        return self._instance._config


# ======== 兼容旧 API ========
def load_config() -> AppConfig:
    """加载配置（兼容旧代码）

    Returns:
        AppConfig: 应用配置对象
    """
    return ConfigCenter().get()
