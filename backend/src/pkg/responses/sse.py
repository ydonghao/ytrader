# SSE (Server-Sent Events) 响应类
# 遵循 HTTP/JSON 接口事实标准：接口字段使用 camelCase，内部代码使用 snake_case
"""
SSE (Server-Sent Events) 响应模块

用于服务器向客户端推送实时事件流，遵循 SSE 协议规范。

HTTP 响应头：
    Content-Type: text/event-stream
    Cache-Control: no-cache
    Connection: keep-alive

SSE 事件格式：
    event: message
    data: {"code":0,"msg":"success","event":"message","data":{...}}

使用示例：
    from src.pkg.responses.sse import SseResponse, StreamEvent

    # 创建消息事件
    event = SseResponse.message({"content": "Hello"})

    # 转换为 SSE 格式字符串
    sse_string = event.to_sse_string()

    # 在 FastAPI 中使用
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    @app.get("/stream")
    async def stream():
        async def event_generator():
            yield SseResponse.start({"session_id": "123"}).to_sse_string()
            yield SseResponse.message({"content": "Hello"}).to_sse_string()
            yield SseResponse.done().to_sse_string()
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Optional, TypeVar
import json

T = TypeVar("T")


class StreamEvent:
    """
    流事件类型常量

    定义 SSE 和 Streamable HTTP 协议中的事件类型。
    """

    # ======== 标准事件类型 ========

    """流开始事件"""
    START: str = "start"

    """消息事件"""
    MESSAGE: str = "message"

    """错误事件"""
    ERROR: str = "error"

    """流结束事件"""
    DONE: str = "done"

    # ======== 工作流事件类型 ========

    """工作流开始"""
    WORKFLOW_START: str = "workflow_start"

    """工作流成功"""
    WORKFLOW_SUCCESS: str = "workflow_success"

    """工作流失败"""
    WORKFLOW_FAILED: str = "workflow_failed"

    """工作流取消"""
    WORKFLOW_CANCEL: str = "workflow_cancel"

    """节点开始"""
    NODE_START: str = "node_start"

    """节点结束"""
    NODE_END: str = "node_end"

    """节点流式输出"""
    NODE_STREAMING_OUTPUT: str = "node_streaming_output"

    """节点错误"""
    NODE_ERROR: str = "node_error"


@dataclass
class SseResponse(Generic[T]):
    """
    SSE (Server-Sent Events) 响应体

    用于服务器向客户端推送实时事件流。

    Attributes:
        code: 响应码 (0=成功)
        msg: 响应消息
        event: 事件类型
        data: 事件数据
        id: 事件ID（可选）
        retry: 重试间隔毫秒（可选）
    """

    code: int = 0
    msg: str = "success"
    event: str = StreamEvent.MESSAGE
    data: Optional[T] = None
    id: Optional[str] = None
    retry: Optional[int] = None

    # ======== 静态工厂方法 - 标准事件 ========

    @classmethod
    def message(cls, data: T, msg: str = "success") -> "SseResponse[T]":
        """
        创建消息事件

        Args:
            data: 事件数据
            msg: 响应消息

        Returns:
            SseResponse 实例
        """
        return cls(code=0, msg=msg, event=StreamEvent.MESSAGE, data=data)

    @classmethod
    def start(cls, data: T = None) -> "SseResponse[T]":
        """
        创建开始事件

        Args:
            data: 事件数据

        Returns:
            SseResponse 实例
        """
        return cls(code=0, msg="success", event=StreamEvent.START, data=data)

    @classmethod
    def done(cls, data: T = None) -> "SseResponse[T]":
        """
        创建完成事件

        Args:
            data: 事件数据

        Returns:
            SseResponse 实例
        """
        return cls(code=0, msg="success", event=StreamEvent.DONE, data=data)

    @classmethod
    def error(cls, code: int, msg: str, data: T = None) -> "SseResponse[T]":
        """
        创建错误事件

        Args:
            code: 错误码
            msg: 错误消息
            data: 错误详情

        Returns:
            SseResponse 实例
        """
        return cls(code=code, msg=msg, event=StreamEvent.ERROR, data=data)

    # ======== 静态工厂方法 - 自定义事件 ========

    @classmethod
    def of(
        cls,
        event: str,
        data: T,
        code: int = 0,
        msg: str = "success",
        id: Optional[str] = None,
        retry: Optional[int] = None,
    ) -> "SseResponse[T]":
        """
        创建自定义事件

        Args:
            event: 事件类型
            data: 事件数据
            code: 响应码
            msg: 响应消息
            id: 事件ID
            retry: 重试间隔（毫秒）

        Returns:
            SseResponse 实例
        """
        return cls(
            code=code,
            msg=msg,
            event=event,
            data=data,
            id=id,
            retry=retry,
        )

    # ======== 辅助方法 ========

    @property
    def is_success(self) -> bool:
        """是否成功"""
        return self.code == 0

    @property
    def is_error(self) -> bool:
        """是否是错误事件"""
        return self.event == StreamEvent.ERROR

    @property
    def is_done(self) -> bool:
        """是否是完成事件"""
        return self.event == StreamEvent.DONE

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "code": self.code,
            "msg": self.msg,
            "event": self.event,
        }
        if self.data is not None:
            result["data"] = self.data
        return result

    def to_sse_string(self) -> str:
        """
        转换为 SSE 格式字符串

        Returns:
            SSE 格式字符串，如: "event: message\\ndata: {...}\\n\\n"
        """
        lines = []

        if self.id is not None:
            lines.append(f"id: {self.id}")

        if self.event is not None:
            lines.append(f"event: {self.event}")

        if self.retry is not None:
            lines.append(f"retry: {self.retry}")

        # 序列化数据为 JSON
        json_data = json.dumps(self.to_dict(), ensure_ascii=False, default=str)
        lines.append(f"data: {json_data}")

        return "\n".join(lines) + "\n\n"


@dataclass
class StreamableResponse(Generic[T]):
    """
    Streamable HTTP 响应体

    基于 MCP (Model Context Protocol) 的 Streamable HTTP transport 规范，
    支持在单个 HTTP 请求/响应中进行双向流式通信。

    请求格式：
        POST /mcp HTTP/1.1
        Content-Type: application/json
        Accept: text/event-stream

        {
            "jsonrpc": "2.0",
            "id": "req_123",
            "method": "tools/call",
            "params": {...}
        }

    响应格式：
        event: message
        data: {"jsonrpc":"2.0","id":"req_123","result":{...}}

    Attributes:
        jsonrpc: JSON-RPC 版本
        id: 请求/响应 ID
        method: 方法名（仅请求）
        params: 请求参数（仅请求）
        result: 响应结果（仅响应）
        error: 错误信息（仅错误响应）
        event: 事件类型
    """

    id: str
    jsonrpc: str = "2.0"
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[T] = None
    error: Optional[Dict[str, Any]] = None
    event: str = StreamEvent.MESSAGE
    JSONRPC_VERSION: str = "2.0"

    # ======== 静态工厂方法 - 响应 ========

    @classmethod
    def message(cls, id: str, result: T) -> "StreamableResponse[T]":
        """
        创建消息响应

        Args:
            id: 请求ID
            result: 结果数据

        Returns:
            StreamableResponse 实例
        """
        return cls(id=id, result=result, event=StreamEvent.MESSAGE)

    @classmethod
    def done(cls, id: str, result: T = None) -> "StreamableResponse[T]":
        """
        创建完成响应

        Args:
            id: 请求ID
            result: 结果数据

        Returns:
            StreamableResponse 实例
        """
        return cls(id=id, result=result, event=StreamEvent.DONE)

    @classmethod
    def error(
        cls,
        id: str,
        code: int,
        message: str,
        data: Any = None,
    ) -> "StreamableResponse[T]":
        """
        创建错误响应

        Args:
            id: 请求ID
            code: 错误码
            message: 错误消息
            data: 错误详情

        Returns:
            StreamableResponse 实例
        """
        error_info = {"code": code, "message": message}
        if data is not None:
            error_info["data"] = data
        return cls(id=id, error=error_info, event=StreamEvent.ERROR)

    # ======== 静态工厂方法 - 请求 ========

    @classmethod
    def request(
        cls,
        id: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> "StreamableResponse[T]":
        """
        创建请求

        Args:
            id: 请求ID
            method: 方法名
            params: 请求参数

        Returns:
            StreamableResponse 实例
        """
        return cls(id=id, method=method, params=params, event=StreamEvent.MESSAGE)

    # ======== 辅助方法 ========

    @property
    def is_error(self) -> bool:
        """是否是错误响应"""
        return self.error is not None

    @property
    def is_done(self) -> bool:
        """是否是完成响应"""
        return self.event == StreamEvent.DONE

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result: Dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
        }

        if self.method is not None:
            result["method"] = self.method

        if self.params is not None:
            result["params"] = self.params

        if self.result is not None:
            result["result"] = self.result

        if self.error is not None:
            result["error"] = self.error

        return result

    def to_sse_string(self) -> str:
        """
        转换为 SSE 格式字符串

        Returns:
            SSE 格式字符串
        """
        lines = []

        if self.event is not None:
            lines.append(f"event: {self.event}")

        json_data = json.dumps(self.to_dict(), ensure_ascii=False, default=str)
        lines.append(f"data: {json_data}")

        return "\n".join(lines) + "\n\n"


@dataclass
class ChunkData:
    """
    流式数据块

    用于表示流式传输中的单个数据块。

    Attributes:
        content: 数据内容
        index: 数据块索引
        finished: 是否是最后一个数据块
    """

    content: str
    index: int = 0
    finished: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "content": self.content,
            "index": self.index,
            "finished": self.finished,
        }