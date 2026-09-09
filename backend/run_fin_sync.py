#!/usr/bin/env python
"""全量财务同步启动脚本（后台友好版）。

禁用 tqdm 进度条输出（避免后台进程 stderr 被刷爆），
降低 socket 超时让卡死请求快速失败。
"""
import os
# 必须在 import akshare 之前设置
os.environ["TQDM_DISABLE"] = "1"
os.environ["LOGURU_LEVEL"] = "ERROR"

import socket
socket.setdefaulttimeout(20)  # 降低超时，卡死请求 20s 快速失败

import sys
import warnings
warnings.filterwarnings("ignore")

_BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BACKEND)

import logging
# 日志同时写文件 + stdout；文件日志保证后台运行时进度不丢
_fh = logging.FileHandler(os.path.join(_BACKEND, "logs", "fin_sync_detail.log"), encoding="utf-8")
_sh = logging.StreamHandler(sys.stdout)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[_fh, _sh],
)
# 压制噪音日志
logging.getLogger("conf").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

from src.domain.market.sync.jobs.financial_full_sync import run

if __name__ == "__main__":
    run(
        markets=os.environ.get("FIN_MARKETS", "A"),
        symbols=None,
        statements="income,balance,cashflow,abstract",
        earnings=os.environ.get("FIN_EARNINGS", "1") == "1",
        max_workers=int(os.environ.get("FIN_WORKERS", "6")),
        rate_delay=0.15,
        resume=True,
    )
