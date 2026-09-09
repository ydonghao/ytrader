"""股票投资课程簇 7——银行/金融业专项（doc 20）纯函数。

通用质量模块（quality.py）面向工商企业，不覆盖银行监管指标。本模块实现
课程 doc 20（招行案例）的五项银行业核心指标：

    7.1 存贷比          贷款总量 / 存款总量
    7.2 NIM 净利息收益率 (利息收入 − 利息支出) / 生息资产
       NIS 净利差       平均贷款利率 − 平均存款利率
    7.3 拨备覆盖率      贷款损失准备 / 不良贷款余额
    7.4 不良贷款率 NPL  不良贷款 / 贷款总额
    7.5 银行营收拆分    净利息收入 + 手续费净收入 + 其他

数据可得性
-----------
- 利息收入/利息支出/手续费收支/发放贷款及垫款/吸收存款/贷款损失准备：
  银行三大报表科目，存在于 ``stock_financial_detail.detail`` JSONB，
  可用 :func:`extract_bank_subjects` 抽取（best-effort）。
- **不良贷款余额**：监管指标，不在三大报表；需调用方从银行专项数据源
  （如银保监/年报附录/akshare 银行业专项接口）供给，传 ``npl_balance`` 参数。

全部纯函数，无 DB/IO 依赖，便于单测。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

try:
    from src.infra.database.market.financial_full import parse_amount
except Exception:  # noqa: BLE001
    parse_amount = None


# ── detail JSONB 银行科目抽取（best-effort，多候选兼容 akshare 列名差异）──────

# 银行三大报表特殊科目 → 规范英文键。
_BANK_SUBJECT_MAP = {
    "interest_income": ["利息收入", "利息净收入-利息收入"],
    "interest_expense": ["利息支出", "利息净收入-利息支出"],
    "fee_income": ["手续费及佣金收入"],
    "fee_expense": ["手续费及佣金支出"],
    "loans_balance": ["发放贷款及垫款", "贷款及垫款"],
    "deposits_balance": ["吸收存款"],
    "loan_loss_provision": ["贷款损失准备"],
}


def extract_bank_subjects(detail) -> dict:
    """从单条报表的 detail JSONB 抽取银行科目为规范英文键（best-effort）。

    Args:
        detail: stock_financial_detail.detail（dict）；非 dict 返回 {}。

    Returns:
        {interest_income, interest_expense, fee_income, fee_expense,
         loans_balance, deposits_balance, loan_loss_provision}（缺失则不出现）。
    """
    out: dict = {}
    if not isinstance(detail, dict):
        return out
    for eng, candidates in _BANK_SUBJECT_MAP.items():
        for k in candidates:
            if k in detail:
                v = detail[k]
                if parse_amount is not None:
                    v = parse_amount(v)
                else:
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        v = None
                if v is not None and math.isfinite(v):
                    out[eng] = v
                break
    return out


# ── 7.1 存贷比 ───────────────────────────────────────────────────────────────

@dataclass
class LoanDepositRatio:
    ratio: float
    verdict: str   # idle_low / normal / high_stretch


def loan_to_deposit_ratio(
    loans_balance: Optional[float],
    deposits_balance: Optional[float],
) -> Optional[LoanDepositRatio]:
    """贷款总量 / 存款总量（doc 20）。

    课程逻辑：过低（资金闲置拖累利润）、过高（吸储不足、流动性紧张）。
    监管原口径 75%（已取消硬约束），课程案例招行约 0.80~0.90 健康区间。

    判定：<0.80 ``idle_low``（资金闲置）/ 0.80~1.10 ``normal`` / >1.10 ``high_stretch``。
    """
    if loans_balance is None or deposits_balance is None or deposits_balance <= 0:
        return None
    r = loans_balance / deposits_balance
    if r < 0.80:
        verdict = "idle_low"
    elif r <= 1.10:
        verdict = "normal"
    else:
        verdict = "high_stretch"
    return LoanDepositRatio(ratio=r, verdict=verdict)


# ── 7.2 NIM / NIS ────────────────────────────────────────────────────────────

@dataclass
class NetInterestMargin:
    nim: float              # 净利息收益率 = 净利息收入 / 生息资产
    verdict: str            # healthy / normal / pressured


def net_interest_margin(
    interest_income: Optional[float],
    interest_expense: Optional[float],
    earning_assets: Optional[float],
) -> Optional[NetInterestMargin]:
    """(利息收入 − 利息支出) / 生息资产 → NIM（doc 20）。

    课程阈值：~2.5% 健康、~1.8% 承压。

    判定：>=2.5% ``healthy`` / 1.8%~2.5% ``normal`` / <1.8% ``pressured``。
    ``earning_assets`` 取平均生息资产最佳；期末值（如发放贷款+金融投资）可作 proxy。
    """
    if (interest_income is None or interest_expense is None
            or earning_assets is None or earning_assets <= 0):
        return None
    nim = (interest_income - interest_expense) / earning_assets
    if nim >= 0.025:
        verdict = "healthy"
    elif nim >= 0.018:
        verdict = "normal"
    else:
        verdict = "pressured"
    return NetInterestMargin(nim=nim, verdict=verdict)


def net_interest_spread(
    avg_loan_rate: Optional[float],
    avg_deposit_rate: Optional[float],
) -> Optional[float]:
    """净利差 NIS = 平均贷款利率 − 平均存款利率（doc 20）。

    课程：正常 ~2.5%。需调用方提供平均贷款/存款利率（不在三大报表）。
    """
    if avg_loan_rate is None or avg_deposit_rate is None:
        return None
    return avg_loan_rate - avg_deposit_rate


# ── 7.3 拨备覆盖率 ───────────────────────────────────────────────────────────

@dataclass
class ProvisionCoverage:
    ratio: float            # 贷款损失准备 / 不良贷款
    verdict: str            # top / solid / low (监管红线 150%)


def provision_coverage_ratio(
    loan_loss_provision: Optional[float],
    npl_balance: Optional[float],
) -> Optional[ProvisionCoverage]:
    """贷款损失准备 / 不良贷款余额 → 拨备覆盖率（doc 20）。

    课程阈值：头部 ~400%（招行）/ 行业 ~250%；监管红线 150%。

    判定：>=300% ``top`` / 150%~300% ``solid`` / <150% ``low``（监管红线）。
    ``npl_balance`` 来自银行监管数据源（不在三大报表），需调用方供给。
    """
    if loan_loss_provision is None or npl_balance is None or npl_balance <= 0:
        return None
    r = loan_loss_provision / npl_balance
    if r >= 3.0:
        verdict = "top"
    elif r >= 1.5:
        verdict = "solid"
    else:
        verdict = "low"
    return ProvisionCoverage(ratio=r, verdict=verdict)


# ── 7.4 不良贷款率 NPL ───────────────────────────────────────────────────────

@dataclass
class NplRatio:
    ratio: float
    verdict: str   # excellent / normal / high (5% 监管红线)


def npl_ratio(
    npl_balance: Optional[float],
    total_loans: Optional[float],
) -> Optional[NplRatio]:
    """不良贷款 / 贷款总额 → 不良率（doc 20）。

    课程阈值：<1% 一梯队资产质量；5% 为监管关注红线。

    判定：<1% ``excellent`` / 1%~2% ``normal`` / >=2% ``high``。
    """
    if npl_balance is None or total_loans is None or total_loans <= 0:
        return None
    r = npl_balance / total_loans
    if r < 0.01:
        verdict = "excellent"
    elif r < 0.02:
        verdict = "normal"
    else:
        verdict = "high"
    return NplRatio(ratio=r, verdict=verdict)


# ── 7.5 银行营收拆分 ────────────────────────────────────────────────────────

@dataclass
class BankRevenueSplit:
    net_interest_income: float       # 利息收入 − 利息支出
    fee_income_net: float            # 手续费收入 − 手续费支出
    other_income: float
    total_revenue: float
    interest_share: float            # 净利息收入占比
    fee_share: float                 # 手续费净收入占比


def bank_revenue_split(
    interest_income: Optional[float],
    interest_expense: Optional[float],
    fee_income: Optional[float] = None,
    fee_expense: Optional[float] = None,
    other_income: float = 0.0,
) -> Optional[BankRevenueSplit]:
    """银行营收 = 净利息收入 + 手续费净收入 + 其他（doc 20）。

    课程逻辑：净利息收入 = 贷款利息 − 存款利息；非利息收入（手续费/中收）
    占比高代表轻资本、护城河强（招行中收占比领先）。

    Args:
        interest_income/interest_expense: 利息收支。
        fee_income/fee_expense: 手续费及佣金收支（可空，缺失按 0）。
        other_income: 其他业务收入。

    Returns:
        BankRevenueSplit；利息收支缺失返回 None。
    """
    if interest_income is None or interest_expense is None:
        return None
    nii = interest_income - interest_expense
    fee_in = fee_income or 0.0
    fee_out = fee_expense or 0.0
    fee_net = fee_in - fee_out
    total = nii + fee_net + other_income
    if total <= 0:
        return None
    return BankRevenueSplit(
        net_interest_income=nii,
        fee_income_net=fee_net,
        other_income=other_income,
        total_revenue=total,
        interest_share=nii / total,
        fee_share=fee_net / total,
    )


# ── 聚合：银行专项报告 ──────────────────────────────────────────────────────

def compute_bank_report(
    fin: dict,
    *,
    npl_balance: Optional[float] = None,
    earning_assets: Optional[float] = None,
) -> dict:
    """聚合银行专项指标（接 detail 抽取或显式输入）。

    Args:
        fin: 基本面 dict，key 用 extract_bank_subjects 的英文键
             （interest_income / interest_expense / fee_income / fee_expense /
              loans_balance / deposits_balance / loan_loss_provision）。
        npl_balance:     不良贷款余额（监管数据源供给，三大表无）。
        earning_assets:  生息资产（缺省用 loans_balance 作 proxy）。

    Returns:
        {loan_deposit, nim, provision_coverage, npl, revenue_split} 各项含
        ``ratio/verdict``；数据缺失的项为 None。
    """
    ea = earning_assets if earning_assets is not None else fin.get("loans_balance")
    return {
        "loan_deposit": _maybe(loan_to_deposit_ratio,
                               fin.get("loans_balance"), fin.get("deposits_balance")),
        "nim": _maybe(net_interest_margin,
                      fin.get("interest_income"), fin.get("interest_expense"), ea),
        "provision_coverage": _maybe(provision_coverage_ratio,
                                     fin.get("loan_loss_provision"), npl_balance),
        "npl": _maybe(npl_ratio, npl_balance, fin.get("loans_balance")),
        "revenue_split": bank_revenue_split(
            fin.get("interest_income"), fin.get("interest_expense"),
            fin.get("fee_income"), fin.get("fee_expense"),
        ),
    }


def _maybe(fn, *args):
    """调用 fn，失败（None）返回 None 而非抛错。"""
    try:
        return fn(*args)
    except Exception:  # noqa: BLE001
        return None
