"""持仓论点路由（spec §5）。注意 /events/list 必须先于 /{thesis_id}。"""
from typing import Any, Optional

from fastapi import APIRouter, Body

from src.pkg import responses

from src.api.handler.thesis_handler import (
    add_journal_note,
    add_ladder_fill,
    add_note,
    add_pass,
    closed_perf,
    pipeline,
    stress_test,
    thermometer_backtest,
    calibration,
    delete_ladder_fill,
    delete_note,
    delete_pass,
    list_notes,
    list_pass,
    update_note,
    capital_allocation_report,
    compare_report,
    dividend_calendar,
    portfolio_risk_report,
    capital_events_list,
    conditions_backtest,
    position_size,
    close_thesis,
    create_thesis,
    get_journal,
    get_thesis,
    list_events,
    list_mines,
    list_theses,
    thermometer,
    mark_event_read,
    mark_reviewed,
    replace_conditions,
    review_summary,
    run_reeval,
    thermometer_history,
    scan_mines,
    sell_check,
    update_thesis,
)

router = APIRouter(prefix="/thesis", tags=["thesis"])


@router.get("")
def get_theses(status: Optional[str] = None) -> Any:
    """论点列表（实时盈亏/条件汇总/最近重估verdict/复检提醒）。"""
    return list_theses(status)


@router.post("")
def post_thesis(payload: dict = Body(...)) -> Any:
    """登记论点（服务端抓 snapshot）。"""
    return create_thesis(payload)


@router.get("/events/list")
def get_events(unread: bool = False) -> Any:
    """事件列表（预警中心持仓论点分区）。"""
    return list_events(unread)


@router.put("/events/{event_id}/read")
def put_event_read(event_id: int) -> Any:
    """标记事件已读。"""
    return mark_event_read(event_id)


@router.get("/capital-allocation/{symbol}")
def get_capital_allocation(symbol: str) -> Any:
    """管理层与资本配置四维报告（分红/分红率/ROIC/筹码）。"""
    return capital_allocation_report(symbol)


@router.get("/capital-events/{symbol}")
def get_capital_events(symbol: str, months: int = 24) -> Any:
    """近 N 月回购/增减持事件列表。"""
    return capital_events_list(symbol, months)


@router.post("/conditions-backtest")
def post_conditions_backtest(payload: dict = Body(...)) -> Any:
    """条件历史回测：{symbol, conditions[], lookback?}。"""
    return conditions_backtest(payload)


@router.get("/thermometer/backtest")
def get_thermometer_backtest() -> Any:
    """水位策略历史回测——检验建议仓位本身。"""
    return thermometer_backtest()


@router.get("/stress-test")
def get_stress_test() -> Any:
    """组合历史极端窗口压力测试。"""
    return stress_test()


@router.post("/weekly-report/generate")
def post_weekly_report() -> Any:
    """手动生成周报（自动 job 在周日 20:00）。"""
    from src.domain.market.thesis.weekly_report import collect_and_save
    return responses.success(collect_and_save())


@router.get("/thermometer")
def get_thermometer(symbol: str = "sh000300",
                    gdp: float = 140.0) -> Any:
    """全市场温度计：ERP 五档+分位+巴菲特+仓位水位。"""
    return thermometer(symbol, gdp)


@router.get("/thermometer/history")
def get_thermometer_history(symbol: str = "sh000300",
                            days: int = 365) -> Any:
    """温度历史序列（日快照，含回填）。"""
    return thermometer_history(symbol, days)


@router.get("/mines")
def get_mines(level: Optional[str] = None,
              limit: int = 100) -> Any:
    """排雷名单（high/medium 优先展示）。"""
    return list_mines(level, limit)


@router.post("/mines/scan")
def post_mines_scan(payload: dict = Body(...)) -> Any:
    """手动排雷扫描 {scope: positions|market}。"""
    return scan_mines(payload)


@router.get("/position-size/{symbol}")
def get_position_size(symbol: str,
                      capital: float = 1000000.0) -> Any:
    """仓位建议：质量×低估→档位+半凯利+单票上限+三档建仓。"""
    return position_size(symbol, capital)


@router.get("/compare")
def get_compare(symbols: str) -> Any:
    """候选对比：?symbols=a,b,c（≤4）。"""
    return compare_report(symbols.split(","))


@router.get("/dividend-calendar")
def get_dividend_calendar() -> Any:
    """持仓股息现金流：未来12月排期+增速。"""
    return dividend_calendar()


@router.get("/notes")
def get_notes(symbol: Optional[str] = None) -> Any:
    """研究笔记列表（可按 symbol 过滤）。"""
    return list_notes(symbol)


@router.post("/notes")
def post_note(payload: dict = Body(...)) -> Any:
    """新建研究笔记。"""
    return add_note(payload)


@router.put("/notes/{note_id}")
def put_note(note_id: int, payload: dict = Body(...)) -> Any:
    """更新笔记。"""
    return update_note(note_id, payload)


@router.delete("/notes/{note_id}")
def del_note(note_id: int) -> Any:
    """删除笔记。"""
    return delete_note(note_id)


@router.get("/closed-performance")
def get_closed_performance() -> Any:
    """关闭论点后续表现——卖出决策反馈。"""
    return closed_perf()


@router.get("/pipeline")
def get_pipeline() -> Any:
    """研究管道：阶段漏斗（零新表，数据推导）。"""
    return pipeline()


@router.get("/portfolio-risk")
def get_portfolio_risk() -> Any:
    """组合层风险：行业集中度/相关性/加权估值。"""
    return portfolio_risk_report()


@router.get("/review")
def get_review() -> Any:
    """复盘汇总：stale 提醒 + 关闭论点统计 + 最近决策。"""
    return review_summary()


@router.post("/review")
def post_review(payload: dict = Body(...)) -> Any:
    """标记已复盘（落 review_log）。"""
    return mark_reviewed(payload)


@router.get("/pass")
def get_pass() -> Any:
    """放弃决策列表 + 错过复盘（放弃后个股 vs 同窗口基准）。"""
    return list_pass()


@router.post("/pass")
def post_pass(payload: dict = Body(...)) -> Any:
    """记一笔放弃决策（研究过但决定不买，服务端抓快照）。"""
    return add_pass(payload)


@router.delete("/pass/{pass_id}")
def del_pass(pass_id: int) -> Any:
    """删除一条放弃记录。"""
    return delete_pass(pass_id)


@router.get("/calibration")
def get_calibration() -> Any:
    """信心度校准：已关闭论点按登记时信心分组胜率/盈亏。"""
    return calibration()


@router.get("/{thesis_id}")
def get_thesis_detail(thesis_id: int) -> Any:
    """详情：论点+条件+快照+重估历史。"""
    return get_thesis(thesis_id)


@router.put("/{thesis_id}")
def put_thesis(thesis_id: int, payload: dict = Body(...)) -> Any:
    """更新基础字段/决策。"""
    return update_thesis(thesis_id, payload)


@router.post("/{thesis_id}/close")
def post_close(thesis_id: int, payload: dict = Body(...)) -> Any:
    """关闭论点（thesis_broken/valuation_reached/better_alt/manual）。"""
    return close_thesis(thesis_id, payload)


@router.get("/{thesis_id}/sell-check")
def get_sell_check(thesis_id: int) -> Any:
    """四区卖出体检报告（实时聚合）。"""
    return sell_check(thesis_id)


@router.post("/{thesis_id}/reeval")
def post_reeval(thesis_id: int) -> Any:
    """手动重估。"""
    return run_reeval(thesis_id)


@router.get("/{thesis_id}/journal")
def get_thesis_journal(thesis_id: int) -> Any:
    """单论点决策日志时间线。"""
    return get_journal(thesis_id)


@router.post("/{thesis_id}/journal")
def post_thesis_journal(thesis_id: int,
                        payload: dict = Body(...)) -> Any:
    """手动手记。"""
    return add_journal_note(thesis_id, payload)


@router.post("/{thesis_id}/ladder-fills")
def post_ladder_fill(thesis_id: int,
                     payload: dict = Body(...)) -> Any:
    """标记一档建仓成交。"""
    return add_ladder_fill(thesis_id, payload)


@router.delete("/{thesis_id}/ladder-fills/{fill_id}")
def del_ladder_fill(thesis_id: int, fill_id: int) -> Any:
    """删除一条成交记录。"""
    return delete_ladder_fill(thesis_id, fill_id)


@router.put("/{thesis_id}/conditions")
def put_conditions(thesis_id: int,
                   payload: dict = Body(...)) -> Any:
    """条件整表替换。"""
    return replace_conditions(thesis_id, payload)
