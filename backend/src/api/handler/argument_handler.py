"""AI 陪练论证库 handler：LLM 产 bull/bear 初稿 → 用户核对 → 归档。

方向约定（六层第⑥件）：AI 只负责初稿与反方论证，事实一律回原始材料
核对；数据上下文全部来自库内真实财报/估值（复用 fundamental_analyst
的装配），prompt 模板 DB 优先（可在提示词控制台改）。
"""
import json  # noqa: F401  (兼容预留)
from typing import Any, Optional

from src.pkg import responses

# 复用基本面深析的数据装配（三大报表时序 + 估值分位）
from src.domain.market.fundamental.agents.fundamental_analyst import (
    collect_fundamental_context,
    format_context_for_prompt,
)
from src.domain.market.intel.agents.base import (
    load_prompt_from_db_or,
    render_prompt,
)

_DEFAULT_PROMPTS = {
    "bull": (
        "你是价值投资的多头陪练。基于下方【数据上下文】，为 {{symbol}} "
        "写一份买入论证初稿：\n"
        "1) 3~5 条论据，每条必须引用上下文里的具体数字；\n"
        "2) 每条论据后注明【风险】：什么数据出现什么变化说明这条论据"
        "不成立；\n"
        "3) 结尾给一段'最强反方观点'——多头最该警惕的一件事；\n"
        "4) 只用上下文中的数字，禁止编造；缺的数据如实说缺。\n"
        "输出 markdown，600 字以内。\n\n【数据上下文】\n{{context}}\n"
        "{{extra}}"
    ),
    "bear": (
        "你是价值投资的空头陪练（红队）。基于下方【数据上下文】，为 "
        "{{symbol}} 写一份看空论证初稿：\n"
        "1) 3~5 条风险论据，每条必须引用上下文里的具体数字"
        "（质量恶化/估值透支/现金流背离/杠杆等角度）；\n"
        "2) 每条论据后注明【反证】：什么数据出现什么变化说明担忧"
        "过度；\n"
        "3) 结尾给一段'最强多头观点'——空头最可能错在哪；\n"
        "4) 只用上下文中的数字，禁止编造；缺的数据如实说缺。\n"
        "输出 markdown，600 字以内。\n\n【数据上下文】\n{{context}}\n"
        "{{extra}}"
    ),
}


def _repo():
    from src.infra.database.market.argument_note import (
        create_argument_note_repository,
    )
    return create_argument_note_repository()


async def _call_llm(prompt: str) -> tuple[str, Optional[str]]:
    """共享单轮调用（infra/llm/single_call，带推理模型短正文重试）。"""
    from src.infra.llm.single_call import complete_with_retry

    return await complete_with_retry(prompt, max_tokens=8000)


def _extra_context(symbol: str) -> str:
    """补强上下文：质量分 + 标准 F-Score（均复用现有 handler）。"""
    import json as _json

    from src.api.handler.financial_detail_handler import (
        f_score_report, quality_report,
    )

    def _unwrap(resp):
        try:
            body = (_json.loads(resp.body) if hasattr(resp, "body")
                    else resp)
            return body.get("data") if body.get("code") == 0 else None
        except Exception:  # noqa: BLE001
            return None

    lines = []
    q = _unwrap(quality_report(symbol))
    if q:
        reds = "、".join(q.get("red_lines") or []) or "无"
        lines.append(
            f"质量分 {q.get('score')}（{q.get('verdict')}），淘汰红线："
            f"{reds}")
    f = _unwrap(f_score_report(symbol))
    if f:
        lines.append(
            f"Piotroski F-Score {f.get('score')}/{f.get('evaluated')}"
            f"（{f.get('verdict')}）")
    return ("\n附加诊断：" + "；".join(lines) + "\n") if lines else ""


async def generate_argument(symbol: str, payload: dict) -> Any:
    """用真实数据上下文生成 bull/bear 初稿（覆盖旧草稿）。"""
    side = (payload.get("side") or "").strip().lower()
    if side not in ("bull", "bear"):
        return responses.error("side 应为 bull|bear")
    sym = symbol.strip().lower()
    try:
        ctx = collect_fundamental_context(sym, periods=8)
        context_text = format_context_for_prompt(ctx)
    except Exception as e:  # noqa: BLE001
        return responses.error(f"数据上下文装配失败: {e}")
    try:
        extra = _extra_context(sym)
    except Exception:  # noqa: BLE001
        extra = ""
    prompt = render_prompt(
        load_prompt_from_db_or(
            f"argument_{side}", _DEFAULT_PROMPTS[side]),
        symbol=sym, context=context_text, extra=extra,
    )
    try:
        content, model = await _call_llm(prompt)
    except RuntimeError as e:
        return responses.error(str(e))
    except Exception as e:  # noqa: BLE001
        return responses.error(f"LLM 调用失败: {e}")
    if not (content or "").strip():
        return responses.error("LLM 返回空内容")
    row = _repo().save_draft(
        sym, side, content.strip(),
        generated_by=model,
        context={"periods": 8, "extra": extra.strip(),
                 "context_head": context_text[:400]},
    )
    row["note"] = "初稿由 AI 生成，归档前请逐条核对数字与原始财报。"
    return responses.success(row)


def list_arguments(symbol: str) -> Any:
    """论证列表（draft 优先 + archived 历史）。"""
    sym = symbol.strip().lower()
    rows = _repo().list(sym)
    return responses.success({
        "rows": rows,
        "drafts": {r["side"]: r for r in rows
                   if r["status"] == "draft"},
    })


def add_manual_argument(payload: dict) -> Any:
    """手动归档一条自己写的论证。"""
    sym = (payload.get("symbol") or "").strip().lower()
    side = (payload.get("side") or "").strip().lower()
    content = (payload.get("content") or "").strip()
    if not sym:
        return responses.error("symbol 必填")
    if side not in ("bull", "bear"):
        return responses.error("side 应为 bull|bear")
    if not content:
        return responses.error("content 必填")
    row = _repo().add_manual({
        "symbol": sym, "side": side, "content": content,
        "evidence": (payload.get("evidence") or "").strip() or None,
    })
    return responses.success(row)


def update_argument(row_id: int, payload: dict) -> Any:
    """编辑论证内容/核实依据（归档前的核对修订）。"""
    content = payload.get("content")
    evidence = payload.get("evidence")
    if content is None and evidence is None:
        return responses.error("content/evidence 至少一项")
    row = _repo().update(row_id, content, evidence)
    if not row:
        return responses.error("论证不存在")
    return responses.success(row)


def archive_argument(row_id: int, payload: dict) -> Any:
    """验证归档——进入该公司正式论证库。"""
    evidence = (payload.get("evidence") or "").strip() or None
    row = _repo().archive(row_id, evidence)
    if not row:
        return responses.error("论证不存在")
    return responses.success(row)


def delete_argument(row_id: int) -> Any:
    ok = _repo().delete(row_id)
    if not ok:
        return responses.error("论证不存在")
    return responses.success({"deleted": True})
