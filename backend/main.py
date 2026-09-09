# FastAPI 启动入口
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env before any import that uses env vars
_loaded = load_dotenv(Path(__file__).parent / ".env")
if _loaded:
    print(f"[env] Loaded .env from {Path(__file__).parent / '.env'}")

from contextlib import asynccontextmanager
import socket
from fastapi import FastAPI
from fastapi.requests import Request
from src.pkg.exceptions.base_exception import BaseAppException
from src.typings.errno.error_no import ErrorNo
from src.pkg import responses
from conf import app_config
from src.api.router.market_router import router as market_router
from src.api.router.trading_router import router as trading_router
from src.api.router.strategy_router import router as strategy_router
from src.api.router.system_router import router as system_router
from src.api.router.ai_chat_router import router as ai_chat_router
from src.api.router.alerts_router import router as alerts_router
from src.api.router.settings_router import router as settings_router
from src.api.router.risk_router import router as risk_router
from src.api.router.t_trading_router import router as t_trading_router
from src.api.router.lt_backtest_router import router as lt_backtest_router
from src.api.router.screener_router import router as screener_router
from src.api.router.factors_router import router as factors_router
from src.api.router.financial_router import router as financial_router
from src.api.router.ws_router import router as ws_router, tick_broadcaster
from src.api.router.report_router import router as report_router
from src.api.router.llm_config_router import router as llm_config_router
from src.api.router.perm_portfolio_router import router as perm_portfolio_router
from src.api.router.watchlist_router import router as watchlist_router
from src.api.router.boom_router import router as boom_router
from src.api.router.board_router import router as board_router
from src.api.router.log_router import router as log_router
from src.api.router.macro_router import router as macro_router
from src.api.router.national_team_router import router as national_team_router
from src.infra.scheduler import setup_scheduler, get_scheduler
from src.api.middleware.logging_middleware import LoggingMiddleware, TraceIdMiddleware
from fastapi import status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from src.pkg.logging.logger import app_logger, setup_logger


def handle_http_exception(req: Request, exc: Exception) -> responses.JSONResponse:
    """处理 HTTP 异常"""
    if hasattr(exc, 'status_code'):
        status_code = exc.status_code
    else:
        status_code = 500

    if hasattr(exc, 'detail'):
        detail = exc.detail
    else:
        detail = str(exc)

    app_logger.error(f'{req.method} {req.url} {str(exc)}')

    # 根据状态码返回不同响应
    if status_code == 401:
        return responses.unauthorized(
            msg=detail if isinstance(detail, str) else "认证失败",
            code=ErrorNo.UNAUTHORIZED
        )
    elif status_code == 403:
        return responses.forbidden(
            msg=detail if isinstance(detail, str) else "禁止访问",
            code=ErrorNo.FORBIDDEN
        )
    elif status_code == 404:
        return responses.not_found(
            msg=detail if isinstance(detail, str) else "资源不存在",
            code=ErrorNo.RESOURCE_NOT_FOUND
        )
    elif status_code == 422:
        return responses.validate_error(
            msg="参数验证失败",
            errors=detail
        )
    else:
        return responses.error(
            msg=detail if isinstance(detail, str) else "请求失败",
            code=ErrorNo.FAIL
        )


def handle_request_validation_error(req: Request, exc: RequestValidationError) -> responses.JSONResponse:
    """处理请求验证错误"""
    app_logger.error(f'{req.method} {req.url} {str(exc.errors())[:100]}')
    return responses.validate_error(
        msg="参数验证失败",
        errors=exc.errors()
    )


_EXCEPTION_HANDLERS = {
    RequestValidationError: handle_request_validation_error,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 进程级 socket 超时兜底：请求处理器内的 akshare/requests 调用默认无超时，
    # 挂死会耗尽 uvicorn 线程池。同步任务模块自带的 setdefaulttimeout(60) 同值幂等。
    socket.setdefaulttimeout(60)

    # Agent system: ensure tables and seed data
    try:
        # Import entities so SQLModel.metadata.create_all picks up the new
        # agent_tool / agent_tool_binding tables on first connection.
        from src.infra.database.agent.entity import (  # noqa: F401
            AgentToolTable, AgentToolBindingTable,
        )
        # Boom radar: import models so create_all picks up boom_* tables
        from src.infra.database.market.boom import (  # noqa: F401
            BoomCandidateTable, BoomKeywordTable, BoomScanHitTable,
        )
        # Import portfolio models so create_all picks up the 5 permanent
        # portfolio tables (instrument/definition/holding/nav/nav_item).
        from src.infra.database.portfolio.models import (  # noqa: F401
            PortfolioInstrument,
            PortfolioDefinition,
            PortfolioHolding,
            PortfolioNav,
            PortfolioNavItem,
        )
        # Import portfolio backtest result model so create_all picks up
        # portfolio_backtest_result table on first connection.
        from src.infra.database.strategy.models import (  # noqa: F401
            PortfolioBacktestResult,
        )
        # Import watchlist models so create_all picks up watchlist_group /
        # watchlist_item tables on first connection.
        from src.infra.database.watchlist.models import (  # noqa: F401
            WatchlistGroup,
            WatchlistItem,
        )
        # Import board model so create_all picks up analysis_board table
        # on first connection.
        from src.infra.database.board.models import (  # noqa: F401
            AnalysisBoard,
        )
        # Import market valuation/dividend models so create_all picks up
        # stock_valuation / stock_dividend tables on first connection.
        from src.infra.database.market.valuation import (  # noqa: F401
            StockValuation,
        )
        from src.infra.database.market.dividend import (  # noqa: F401
            StockDividend,
        )
        # Import market sentiment / shareholder-count models so create_all
        # picks up stock_shareholder_count / north_flow_daily /
        # margin_balance_daily tables on first connection.
        from src.infra.database.market.shareholder_count import (  # noqa: F401
            StockShareholderCount,
        )
        from src.infra.database.market.market_sentiment import (  # noqa: F401
            NorthFlowDaily,
            MarginBalanceDaily,
        )
        from src.infra.database.market.fundamental_report import (  # noqa: F401
            FundamentalReport,
        )
        from src.infra.database.agent.repository import (
            seed_agent_data,
            migrate_agent_tools,
            migrate_macro_prompts,
            migrate_macro_prompts_v2,
        )
        seed_agent_data()
        migrate_agent_tools()
        migrate_macro_prompts()
        migrate_macro_prompts_v2()
        app_logger.info("[Agent] tables migrated and seeded")
    except Exception as e:
        app_logger.warning(f"[Agent] migration/seed failed: {e}")

    # macro_view / macro_indicator 表加列兜底（无 Alembic）
    try:
        from src.infra.database.market.macro_view import ensure_macro_view_columns
        from src.infra.database.market.macro_indicator import (
            ensure_macro_indicator_columns,
        )
        ensure_macro_view_columns()
        ensure_macro_indicator_columns()
        app_logger.info("[Macro] macro tables columns ensured")
    except Exception as e:
        app_logger.warning(f"[Macro] column migration failed: {e}")

    # stock_financial_detail 加列兜底（capex / free_cash_flow）
    try:
        from src.infra.database.market.financial_full import (
            ensure_stock_financial_detail_columns,
        )
        ensure_stock_financial_detail_columns()
        app_logger.info(
            "[Financial] stock_financial_detail columns ensured"
        )
    except Exception as e:
        app_logger.warning(
            f"[Financial] column migration failed: {e}"
        )

    # 启动 APScheduler
    sched = setup_scheduler()
    sched.start()
    app_logger.info("[Scheduler] started, jobs=%s", [j.id for j in sched.get_jobs()])

    # Auto-migrate MiniMax env var to llm_config table
    try:
        from src.infra.database.llm.repository import create_llm_repository
        _llm_repo = create_llm_repository()
        configs = _llm_repo.list_configs()
        if not configs:
            minimax_key = os.environ.get("MINIMAX_API_KEY", "")
            if minimax_key:
                from src.domain.llm.models import LLMConfig
                _llm_repo.create_config(LLMConfig(
                    name="MiniMax",
                    provider_type="openai_chat",
                    base_url="https://api.minimaxi.com/v1",
                    api_key=minimax_key,
                    model="MiniMax-M2.7",
                    is_default=True,
                ))
                app_logger.info("Auto-migrated MINIMAX_API_KEY to llm_config table")
    except Exception as e:
        app_logger.warning(f"MiniMax auto-migration failed: {e}")

    # 启动 WebSocket broadcaster
    import threading
    import asyncio

    def start_broadcaster():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(tick_broadcaster())

    threading.Thread(target=start_broadcaster, daemon=True).start()

    app_logger.info("App startup complete.")
    yield

    # Shutdown
    app_logger.info("App shutdown initiated.")
    get_scheduler().shutdown(wait=False)
    app_logger.info("App shutdown complete.")


def create_app():
    """Create the FastAPI app and include the router."""

    setup_logger()

    app = FastAPI(
        default_response_class=responses.JSONResponse,
        exception_handlers=_EXCEPTION_HANDLERS,
        lifespan=lifespan,
        root_path=f"{app_config.root_path}",
        debug=True
    )

    origins = [
        '*',
    ]

    # 添加中间件（使用类形式，参考 Coze Studio 架构）
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(TraceIdMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.get('/health')
    def get_health():
        return {'status': 'OK'}

    @app.exception_handler(BaseAppException)
    async def app_exception_handler(request: Request, exc: BaseAppException):
        """处理业务异常"""
        return responses.fail(
            msg=exc.message,
            code=exc.code,
            data=exc.detail
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """处理全局异常"""
        app_logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return responses.error(
            msg=str(exc),
            code=ErrorNo.SERVER_ERROR,
            data=None
        )

    # 注册路由
    app_logger.info("Registering routers...")
    app.include_router(market_router, prefix="/api/v1")  # /api/v1/market
    app.include_router(trading_router, prefix="/api/v1")  # /api/v1/trade
    app.include_router(strategy_router, prefix="/api/v1")  # /api/v1/strategy
    app.include_router(system_router, prefix="/api/v1")   # /api/v1/system
    app.include_router(ai_chat_router, prefix="/api/v1")  # /api/v1/ai/chat
    app.include_router(alerts_router, prefix="/api/v1")  # /api/v1/alerts
    app.include_router(settings_router, prefix="/api/v1")  # /api/v1/settings
    app.include_router(risk_router, prefix="/api/v1")      # /api/v1/risk
    app.include_router(t_trading_router, prefix="/api/v1")  # /api/v1/t-trading
    app.include_router(lt_backtest_router, prefix="/api/v1")  # /api/v1/lt-backtest
    app.include_router(screener_router, prefix="/api/v1")  # /api/v1/screener
    app.include_router(factors_router, prefix="/api/v1")    # /api/v1/factors
    app.include_router(financial_router, prefix="/api/v1")  # /api/v1/financial
    app.include_router(ws_router)  # /ws/market/tick/{symbol}
    app.include_router(report_router, prefix="/api/v1")  # /api/v1/report
    app.include_router(llm_config_router, prefix="/api/v1")  # /api/v1/llm
    app.include_router(perm_portfolio_router, prefix="/api/v1")  # /api/v1/perm-portfolio
    app.include_router(watchlist_router, prefix="/api/v1")  # /api/v1/watchlist
    app.include_router(boom_router, prefix="/api/v1")  # /api/v1/boom
    app.include_router(board_router, prefix="/api/v1")  # /api/v1/board
    app.include_router(log_router, prefix="/api/v1")  # /api/v1/logs
    app.include_router(macro_router, prefix="/api/v1")  # /api/v1/macro
    app.include_router(national_team_router, prefix="/api/v1")  # /api/v1/national-team
    app_logger.info("Routers registered.")

    return app


if __name__ == "__main__":
    import uvicorn
    from conf import app_config
    # 端口优先级：BACKEND_PORT 环境变量 > conf/config.yaml server.port
    _port = int(os.environ.get("BACKEND_PORT", app_config.server.port))
    uvicorn.run(create_app(), host="0.0.0.0", port=_port)
