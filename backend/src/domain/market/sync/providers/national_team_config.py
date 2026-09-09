"""国家队配置加载 + 主体名前缀匹配。

配置文件:backend/conf/national_team_entities.yaml
"""
from functools import lru_cache
from pathlib import Path

import yaml

_CONF_PATH = Path(__file__).parent.parent.parent.parent.parent.parent / "conf" / "national_team_entities.yaml"


@lru_cache(maxsize=1)
def load_national_team_config() -> dict:
    """加载并缓存配置。"""
    with open(_CONF_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def match_holder_category(holder_name: str) -> str | None:
    """前缀匹配股东名,返回 category(huijin/zhengjin/safe/social_security)或 None。

    匹配规则:holder_name 以某个前缀开头(去除空格后比较)即命中。
    """
    if not holder_name:
        return None
    name = holder_name.strip()
    cfg = load_national_team_config()
    for category, prefixes in cfg.get("holder_categories", {}).items():
        for prefix in prefixes:
            if name.startswith(prefix.strip()):
                return category
    return None


def get_watch_etfs() -> list[dict]:
    return load_national_team_config().get("watch_etfs", [])


def get_entity_meta() -> dict:
    """6 大国家队主体展示元数据:{category: {display, color, type, desc}}。"""
    return load_national_team_config().get("entity_meta", {})


def get_etf_first_holders() -> list[dict]:
    """ETF 第一大持有人(汇金)占比参考值(慢变量,来自交易所 ETF 季报)。"""
    return load_national_team_config().get("etf_first_holder", [])


def get_backfill_scope() -> list[dict]:
    return load_national_team_config().get("backfill_scope", [])


def get_backfill_from() -> str:
    return load_national_team_config().get("backfill_from", "2015-01-01")
