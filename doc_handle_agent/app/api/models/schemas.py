"""API请求和响应模型."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ========== 文档生成请求/响应 ==========

class GenerateDocumentRequest(BaseModel):
    """生成文档请求."""

    repo_id: str = Field(..., description="仓库ID")
    template_path: str = Field(..., description="模板文件路径")
    output_filename: Optional[str] = Field(
        default=None,
        description="输出文件名（可选，默认自动生成）",
    )


class GenerateDocumentResponse(BaseModel):
    """生成文档响应."""

    flow_id: str = Field(..., description="流程ID")
    status: str = Field(..., description="当前状态")
    repo_id: str = Field(..., description="仓库ID")
    template_path: str = Field(..., description="模板路径")
    output_path: str = Field(..., description="输出路径")
    created_at: str = Field(..., description="创建时间")


# ========== 进度查询响应 ==========

class GenerationProgressResponse(BaseModel):
    """生成进度响应."""

    flow_id: str = Field(..., description="流程ID")
    repo_id: str = Field(..., description="仓库ID")
    status: str = Field(..., description="当前状态")
    progress: float = Field(..., description="进度百分比(0-100)")
    current_step: int = Field(..., description="当前步骤")
    total_steps: int = Field(..., description="总步骤")
    message: str = Field(..., description="状态消息")
    output_path: Optional[str] = Field(None, description="输出文件路径")
    error: Optional[str] = Field(None, description="错误信息")


# ========== 模板相关 ==========

class TemplateParagraphInfo(BaseModel):
    """模板段落信息."""

    id: str = Field(..., description="段落ID")
    is_template: bool = Field(..., description="是否为模板段落")
    text: str = Field(..., description="原始文本")
    is_heading: bool = Field(..., description="是否为标题")
    prompt: Optional[str] = Field(None, description="生成提示词（模板段落）")
    is_list: bool = Field(False, description="是否生成列表")
    min_length: Optional[int] = Field(None, description="最小长度")
    max_length: Optional[int] = Field(None, description="最大长度")
    example: Optional[str] = Field(None, description="内容生成参考示例")


class PreviewTemplateRequest(BaseModel):
    """预览模板请求."""

    template_path: str = Field(..., description="模板文件路径")


class PreviewTemplateResponse(BaseModel):
    """预览模板响应."""

    template_path: str = Field(..., description="模板路径")
    valid: bool = Field(..., description="是否有效")
    message: Optional[str] = Field(None, description="验证消息")
    paragraphs: List[TemplateParagraphInfo] = Field(default=[], description="模板段落列表")


# ========== 系统状态 ==========

class SystemStatusResponse(BaseModel):
    """系统状态响应."""

    status: str = Field(..., description="系统状态")
    active_generations: int = Field(..., description="活动生成任务数")
    version: str = Field(default="1.0.0", description="版本号")


class ActiveGenerationInfo(BaseModel):
    """活动生成任务信息."""

    flow_id: str = Field(..., description="流程ID")
    status: Optional[str] = Field(None, description="当前状态")


# 兼容性导出（保留旧名称以兼容现有代码）
ContentBlockInfo = TemplateParagraphInfo
