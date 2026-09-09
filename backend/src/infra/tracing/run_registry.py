"""活跃 run 注册表 — run_id → threading.Event 取消令牌。

blog 生成跑在后台 daemon 线程里（句柄被丢弃），无法用 asyncio
Task.cancel() 中断。改用进程内注册表 + threading.Event 实现协作式取消：
后台 run 启动时 register() 生成 Event；停止接口 request_cancel() 置位
Event；流水线在节点边界（@agent_node / 每个 trend 循环）is_cancelled()
轮询，检测到则优雅终止。run 结束时 unregister() 清理。

线程安全：所有读写经 _lock 保护。Event 本身是线程安全的。
"""
import threading
from typing import Optional

_lock = threading.Lock()
# run_id → threading.Event；只有"正在运行"的 run 才在这里
_runs: dict[str, threading.Event] = {}


def register(run_id: str) -> threading.Event:
    """注册一个活跃 run，返回其取消令牌 Event（初始未置位）。

    在后台线程 _bg() 开头调用。同一 run_id 重复注册会覆盖旧令牌
    （正常不应发生）。
    """
    with _lock:
        ev = threading.Event()
        _runs[run_id] = ev
        return ev


def is_cancelled(run_id: Optional[str]) -> bool:
    """检查 run 是否被请求取消。run_id 为 None 或已注销则返回 False。"""
    if not run_id:
        return False
    with _lock:
        ev = _runs.get(run_id)
    return ev.is_set() if ev else False


def request_cancel(run_id: str) -> bool:
    """请求取消指定 run。返回 True 表示找到了活跃 run 并已置位。

    前端停止接口调这个。Event 置位后，正在运行的节点会在下一个检查点
    （节点边界）退出；当前节点内的 LLM 调用会跑完。
    """
    with _lock:
        ev = _runs.get(run_id)
    if ev:
        ev.set()
        return True
    return False


def unregister(run_id: str) -> None:
    """注销 run（run 自然结束或失败时调用）。不存在的 run_id 安全忽略。"""
    with _lock:
        _runs.pop(run_id, None)
