"""排雷判定纯函数（价值投资闭环第 5 期）。

三源信号聚合：Altman Z（财务困境）/ Beneish M（盈余操纵）/
fraud 红旗（造假异常）。任一强信号即 high；观察级为 medium。
None 源不参与判定——数据缺失不等于安全，也不触发告警。
"""
from typing import Optional

_Z_LABEL = {
    "distress": "Altman Z 处于困境区（Z<1.81，破产风险）",
    "grey": "Altman Z 灰色区（1.81~2.99）",
}
_M_LABEL = {
    "manipulator": "Beneish M 疑似盈余操纵（M>-1.78）",
    "watch": "Beneish M 观察区（-1.78~-2.22）",
}
_FRAUD_LABEL = {
    "high_risk": "财务红旗≥2项（营收-应收/净利-现金流/存货/毛利率异常）",
    "watch": "财务红旗1项（观察）",
}


def assess_mine(
    z_verdict: Optional[str],
    m_verdict: Optional[str],
    fraud_severity: Optional[str],
) -> dict:
    """三源 → {risk_level: high/medium/clean, reasons: [...]}。"""
    strong, watch, reasons = [], [], []
    if z_verdict in _Z_LABEL:
        (strong if z_verdict == "distress" else watch).append(
            _Z_LABEL[z_verdict]
        )
    if m_verdict in _M_LABEL:
        (strong if m_verdict == "manipulator" else watch).append(
            _M_LABEL[m_verdict]
        )
    if fraud_severity in _FRAUD_LABEL:
        (strong if fraud_severity == "high_risk" else watch).append(
            _FRAUD_LABEL[fraud_severity]
        )
    missing = [
        name for name, v in (
            ("Z", z_verdict), ("M", m_verdict), ("红旗", fraud_severity),
        ) if v is None
    ]
    if missing:
        reasons.append("数据缺失源（不参与判定）：" + "、".join(missing))
    if strong:
        return {"risk_level": "high",
                "reasons": strong + watch + reasons}
    if watch:
        return {"risk_level": "medium", "reasons": watch + reasons}
    return {"risk_level": "clean", "reasons": reasons}
