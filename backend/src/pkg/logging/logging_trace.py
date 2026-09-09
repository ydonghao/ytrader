
import uuid
from src.pkg.logging import logging_context

class LoggingTrace(object):
    @staticmethod
    def set_req_id(req_id: str = None, title="req-id") -> str:
        """
        设置请求唯一ID
        Args:
            req_id: 请求ID 默认None取uuid
            title: 标题 默认req-id

        Returns:
            title:req_id
        """
        req_id = req_id or uuid.uuid4().hex
        req_id = f"{title}:{req_id}"

        logging_context.REQUEST_ID.set(req_id)
        return req_id

    @staticmethod
    def set_trace_id(trace_id: str = None, title="trace-id") -> str:
        """
        设置追踪ID, 可用于一些脚本等场景进行链路追踪
        Args:
            trace_id: 追踪唯一ID 默认None取uuid
            title: 标题 默认 trace-id, 可以用于标识业务

        Returns:
            title:trace_id
        """
        trace_id = trace_id or uuid.uuid4().hex
        trace_id = f"{title}:{trace_id}"

        logging_context.TRACE_ID.set(trace_id)
        return trace_id

    @staticmethod
    def get_req_id() -> str:
        return logging_context.REQUEST_ID.get()

    @staticmethod
    def get_trace_id() -> str:
        return logging_context.TRACE_ID.get()
