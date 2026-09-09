"""
文件相关的 API 模型定义
定义请求和响应的数据结构
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class FileAnalyzeRequest(BaseModel):
    """文件分析请求模型"""
    file_url: Optional[str] = Field(None, description="文件URL，与file二选一")
    output_coordinates: bool = Field(True, description="是否输出坐标信息")


class FileInfoModel(BaseModel):
    """文件信息模型"""
    filename: str = Field(..., description="文件名")
    file_type: str = Field(..., description="文件类型")
    size_bytes: int = Field(..., description="文件大小（字节）")
    page_count: Optional[int] = Field(None, description="页数")
    author: Optional[str] = Field(None, description="作者")
    created_at: Optional[str] = Field(None, description="创建时间")
    modified_at: Optional[str] = Field(None, description="修改时间")


class TextBlockModel(BaseModel):
    """文本块模型"""
    page: int = Field(..., description="页码")
    content: str = Field(..., description="文本内容")
    line_num: str = Field(..., description="行号")
    coordinate: List = Field(default_factory=list, description="坐标信息")


class FileAnalyzeResponse(BaseModel):
    """文件分析响应模型"""
    status: str = Field(..., description="状态")
    file_info: FileInfoModel = Field(..., description="文件信息")
    output: List[TextBlockModel] = Field(..., description="文本块列表")
