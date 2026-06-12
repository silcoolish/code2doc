"""API请求和响应模型."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ========== 文档生成请求/响应 ==========

class GenerateDocumentRequest(BaseModel):
    """生成文档请求."""

    repo_id: str = Field(..., description="仓库ID")
    template_id: str = Field(..., description="文档模板ID")


class GenerateDocumentResponse(BaseModel):
    """生成文档响应."""

    flow_id: str = Field(..., description="流程ID")
    status: str = Field(..., description="当前状态")
    repo_id: str = Field(..., description="仓库ID")
    template_id: str = Field(..., description="文档模板ID")
    document_id: Optional[str] = Field(None, description="生成的文档ID")
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
    started_at: Optional[str] = Field(None, description="开始时间")
    updated_at: Optional[str] = Field(None, description="最近更新时间")
    finished_at: Optional[str] = Field(None, description="结束时间")
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


# ========== 改写相关 ==========

class RewriteBlockRequest(BaseModel):
    """改写文档条目请求."""

    repo_id: str = Field(..., description="仓库ID")
    target_key: str = Field(..., description="目标键")
    target_type: str = Field(default="block", description="目标类型: block/selection")
    block_id: str = Field(..., description="条目ID")
    block_text: Optional[str] = Field(None, description="当前块的纯文本内容")
    selected_text: Optional[str] = Field(None, description="选中文本")
    selection_start: Optional[int] = Field(None, description="选区起始偏移")
    selection_end: Optional[int] = Field(None, description="选区结束偏移")
    prompt: Optional[str] = Field(None, description="补充改写要求")
    preset: Optional[str] = Field(None, description="快捷改写模式")
    action: Optional[str] = Field(None, description="改写动作: rewrite/continue")
    deep_think: bool = Field(default=False, description="是否深度思考")
    document_id: Optional[str] = Field(None, description="文档ID，用于获取文档上下文")


class RewriteBlockResponse(BaseModel):
    """改写文档条目响应."""

    result_text: str = Field(default="", description="改写后的纯文本结果")
    result_markdown: str = Field(default="", description="改写后的 Markdown")
    candidates: List[str] = Field(default=[], description="候选结果列表")
    apply_modes: List[str] = Field(default=[], description="支持的应用方式")
    summary: Optional[str] = Field(None, description="改写摘要")


# 兼容性导出（保留旧名称以兼容现有代码）
ContentBlockInfo = TemplateParagraphInfo
