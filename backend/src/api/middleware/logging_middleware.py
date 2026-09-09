"""
日志中间件
处理请求日志记录和全链路追踪
"""
import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from src.pkg.logging.logging_trace import LoggingTrace
from src.pkg.logging.logger import app_logger


REQUEST_ID_KEY = "X-Request-Id"


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    日志记录中间件
    记录请求处理时间和基本信息
    """

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = (time.time() - start_time) * 1000
        app_logger.info(f"{request.method} {request.url} - {response.status_code} - {process_time:.2f}ms")
        return response


class TraceIdMiddleware(BaseHTTPMiddleware):
    """
    链路追踪中间件
    为每个请求分配唯一的追踪ID
    """

    async def dispatch(self, request: Request, call_next):
        trace_id = str(uuid.uuid4().hex)
        LoggingTrace.set_trace_id(trace_id)
        request.state.trace_id = trace_id
        app_logger.info(f"Assigned Trace ID: {trace_id} for request {request.url}")
        response = await call_next(request)
        response.headers[REQUEST_ID_KEY] = trace_id
        return response
