import logging
import sys
from loguru import logger
from conf.settings import ConfigCenter
from src.pkg.logging.logging_trace import LoggingTrace


def _filter(record):
    record["extra"] = {"trace_id": LoggingTrace.get_trace_id()}
    return True


class InterceptHandler(logging.Handler):
    """把标准库 logging 的记录转发到 loguru。

    项目里 scheduler.py / sync_service.py / quant_daily.py 等大量模块用
    logging.getLogger(__name__)，而服务主日志走 loguru。没有此 handler 时，
    标准 logging 的记录（含 APScheduler 的 misfire 警告、quant job 的成功/失败
    日志）会被 root logger 静默丢弃，导致定时 job 完全无日志可查、出问题无法排查。
    """

    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logger():
    cfg = ConfigCenter().get().logging

    # 清空默认 handler
    logger.remove()

    # 拦截标准 logging → loguru（scheduler/sync 等模块用 logging.getLogger）
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # 控制台输出（开发环境彩色）
    logger.add(
        sys.stdout,
        level=cfg.level,
        format=cfg.format,
        filter=_filter,
        colorize=True,
        backtrace=True,
        diagnose=True
    )

    # 文件输出（按大小切割）
    logger.add(
        "logs/app.log",
        rotation=cfg.rotation,
        retention=cfg.retention,
        level=cfg.level,
        format=cfg.format,
        filter=_filter,
        serialize=cfg.serialize,
        enqueue=True,  # 异步写入
        encoding="utf-8"
    )

    # 错误日志单独存
    logger.add(
        "logs/error.log",
        rotation=cfg.rotation,
        retention=cfg.retention,
        level="ERROR",
        format=cfg.format,
        filter=_filter,
        serialize=cfg.serialize,
        enqueue=True,
        encoding="utf-8"
    )


    return logger

# 单例 logger
app_logger = setup_logger()
# 默认 trace_id 为空字符串，防止 KeyError
app_logger = logger.bind(trace_id="-")
