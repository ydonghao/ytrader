"""
新闻情绪分析器（基于规则）
"""
import re
from typing import Tuple


# 中文情绪词典
POSITIVE_WORDS = {
    "上涨": 0.1, "涨停": 0.5, "增长": 0.15, "利好": 0.2, "盈利": 0.2,
    "成功": 0.1, "突破": 0.15, "创新": 0.1, "优秀": 0.2, "增持": 0.15,
    "推荐": 0.1, "买入": 0.15, "超预期": 0.2, "大幅": 0.1, "强劲": 0.15,
    "首板": 0.2, "连板": 0.3, "爆发": 0.15, "丰收": 0.15, "开门红": 0.15,
    "涨停潮": 0.3, "领涨": 0.15, "涨幅居前": 0.1, "QFII": 0.05, "外资": 0.05,
    "净买入": 0.1, "机构调研": 0.05, "业绩超": 0.15, "分红": 0.1,
}

NEGATIVE_WORDS = {
    "下跌": -0.1, "跌停": -0.5, "亏损": -0.2, "利空": -0.2, "风险": -0.1,
    "问题": -0.1, "困难": -0.1, "下滑": -0.15, "减少": -0.1, "警告": -0.2,
    "减持": -0.15, "卖出": -0.15, "不及预期": -0.15, "大幅下跌": -0.2,
    "净流出": -0.1, "破发": -0.15, "造假": -0.4, "处罚": -0.25, "立案": -0.3,
    "ST": -0.3, "*ST": -0.35, "退市": -0.4, "闪崩": -0.3, "踩雷": -0.3,
    "债务": -0.2, "违约": -0.25, "诉讼": -0.15, "业绩变脸": -0.25,
}

HIGH_IMPORTANCE_PATTERNS = [
    "年报", "季报", "业绩预告", "业绩快报", "重大", "紧急", "突发",
    "重组", "收购", "资产出售", "定向增发", "可转债", "股权激励",
    "退市", "暂停上市", "终止上市", "立案调查", "处罚",
]

MEDIUM_IMPORTANCE_PATTERNS = [
    "公告", "通知", "变更", "调整", "计划", "通过", "审议",
    "分红", "配股", "送股", "扩股", "高管", "董事", "辞职",
]


def analyze(text: str) -> Tuple[str, float, str]:
    """
    分析文本情绪。

    Returns:
        (sentiment, score, importance)
        sentiment: positive / negative / neutral
        score: -1.0 ~ 1.0
        importance: high / medium / low
    """
    if not text:
        return "neutral", 0.0, "low"

    score = 0.0
    words_found = 0

    text_lower = text.lower()

    for word, weight in POSITIVE_WORDS.items():
        if word in text_lower:
            score += weight
            words_found += 1

    for word, weight in NEGATIVE_WORDS.items():
        if word in text_lower:
            score += weight
            words_found += 1

    # 归一化
    if words_found > 0:
        score = max(-1.0, min(1.0, score))

    # 情绪分类
    if score > 0.05:
        sentiment = "positive"
    elif score < -0.05:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    # 重要性评估
    importance = "low"
    if any(p in text for p in HIGH_IMPORTANCE_PATTERNS):
        importance = "high"
    elif any(p in text for p in MEDIUM_IMPORTANCE_PATTERNS):
        importance = "medium"

    return sentiment, score, importance


def extract_keywords(text: str, top_n: int = 10) -> list[str]:
    """提取关键词（简单基于规则）"""
    keywords = []

    # 常见金融关键词
    finance_words = [
        "业绩", "年报", "季报", "增长", "利润", "营收", "股价", "投资",
        "市场", "行业", "政策", "监管", "风险", "机会", "创新", "发展",
        "新能源", "芯片", "人工智能", "医药", "白酒", "银行", "券商",
        "光伏", "锂电池", "新能源汽车", "5G", "半导体", "生物医药",
    ]

    for word in finance_words:
        if word in text:
            keywords.append(word)

    return keywords[:top_n]


def classify_category(title: str, content: str = "") -> str:
    """分类新闻类别"""
    text = (title + " " + content).lower()

    if any(w in text for w in ["年报", "季报", "业绩", "财报", "公告", "净利润"]):
        return "company_announcement"
    elif any(w in text for w in ["政策", "央行", "监管", "法规", "国务院", "证监会"]):
        return "policy_news"
    elif any(w in text for w in ["行情", "指数", "板块", "大盘", "市场"]):
        return "market_news"
    elif any(w in text for w in ["研报", "分析", "评级", "推荐", "目标价"]):
        return "research_report"
    elif any(w in text for w in ["招股", "IPO", "上市", "申购"]):
        return "ipo_news"
    else:
        return "general"
