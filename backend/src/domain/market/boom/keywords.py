# backend/src/domain/market/boom/keywords.py
"""景气信号词典 —— 种子常量 + 分类元数据。

分类英文码入库/API 稳定,中文标签仅展示用。种子词为原文 7 信号 + 同义扩展。
"""
from dataclasses import dataclass

CATEGORIES = (
    "supply_tight",    # 供给紧张
    "boom_up",         # 景气上行
    "beat",            # 超预期
    "price_up",        # 价格上行
    "demand_strong",   # 需求旺盛
    "new_product",     # 新品放量
    "expand",          # 拓展替代
)

CATEGORY_LABELS = {
    "supply_tight": "供给紧张",
    "boom_up": "景气上行",
    "beat": "超预期",
    "price_up": "价格上行",
    "demand_strong": "需求旺盛",
    "new_product": "新品放量",
    "expand": "拓展替代",
}


@dataclass(frozen=True)
class KeywordDef:
    category: str
    keyword: str
    weight: int = 1


SEED_KEYWORDS: tuple[KeywordDef, ...] = (
    KeywordDef("supply_tight", "供不应求", 3),
    KeywordDef("supply_tight", "供给偏紧", 3),
    KeywordDef("supply_tight", "供应紧张", 2),
    KeywordDef("supply_tight", "紧缺", 1),
    KeywordDef("supply_tight", "排队提货", 2),
    KeywordDef("boom_up", "高景气", 3),
    KeywordDef("boom_up", "景气度上行", 3),
    KeywordDef("boom_up", "景气周期向上", 3),
    KeywordDef("boom_up", "行业景气", 2),
    KeywordDef("beat", "超预期", 3),
    KeywordDef("beat", "好于预期", 2),
    KeywordDef("beat", "超出预期", 2),
    KeywordDef("beat", "大超预期", 3),
    KeywordDef("price_up", "价格中枢上涨", 3),
    KeywordDef("price_up", "价格中枢上移", 3),
    KeywordDef("price_up", "量价齐升", 3),
    KeywordDef("price_up", "提价", 2),
    KeywordDef("price_up", "涨价", 2),
    KeywordDef("demand_strong", "需求旺盛", 3),
    KeywordDef("demand_strong", "产销两旺", 3),
    KeywordDef("demand_strong", "满产满销", 3),
    KeywordDef("demand_strong", "订单饱满", 3),
    KeywordDef("demand_strong", "需求强劲", 2),
    KeywordDef("new_product", "新品上市", 2),
    KeywordDef("new_product", "新品放量", 3),
    KeywordDef("new_product", "渗透率提升", 2),
    KeywordDef("new_product", "产品结构升级", 2),
    KeywordDef("expand", "超预期拓展", 3),
    KeywordDef("expand", "市场拓展", 2),
    KeywordDef("expand", "国产替代", 2),
    KeywordDef("expand", "新客户突破", 2),
)


def default_keywords() -> list[KeywordDef]:
    return list(SEED_KEYWORDS)
