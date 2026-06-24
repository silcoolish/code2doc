"""Agent状态定义."""

from typing import Any, Dict, List, Optional, TypedDict

from app.domain.model import (
    GenerationStatus,
    ImageInfo,
    TemplateBlock,
)

__all__ = [
    "GenerationStatus",
    "TemplateBlock",
    "ImageInfo",
    "AgentState",
    "create_initial_state",
]


class AgentState(TypedDict):
    """Agent工作流状态."""

    # 输入参数
    repo_id: str
    template_id: str  # 模板ID（替代原来的template_path）
    workspace_auth_token: Optional[str]  # 回调 workspace_service 使用的当前用户登录态

    # 解析结果 - 模板block列表（新结构）
    blocks: List[TemplateBlock]

    # 图片信息
    # {block ID: 图片信息列表}
    generated_images: Dict[str, List[ImageInfo]]

    # 进度
    total_blocks: int  # 总block数
    status: str
    message: str

    # 错误信息
    error: Optional[str]

    # 生成的文档ID
    document_id: Optional[str]

    # 文档标题
    title: Optional[str]

    # 当前执行的节点名称
    current_node: Optional[str]

    # 细粒度进度
    progress: Optional[float]
    __progress_reporter: Optional[Any]
    started_at: Optional[str]
    updated_at: Optional[str]
    finished_at: Optional[str]

    # 策略选择结果
    selected_strategy: Optional[str]  # 选中的策略名称
    estimated_tokens: int  # 预估token数

    # 构建后的文档blocks（用于保存到workspace）
    doc_blocks: List[Dict[str, Any]]

    # 向后兼容的字段
    template_path: str
    paragraphs: List  # 旧字段，保留兼容
    current_paragraph_index: int  # 旧字段，保留兼容
    total_paragraphs: int  # 旧字段，保留兼容


def create_initial_state(
    repo_id: str,
    template_id: str,
    template_path: str = "",
    workspace_auth_token: Optional[str] = None,
) -> AgentState:
    """创建初始状态.

    Args:
        repo_id: 仓库ID
        template_id: 模板ID
        template_path: 模板路径（保留向后兼容）
        workspace_auth_token: 回调workspace_service使用的登录态

    Returns:
        初始Agent状态
    """
    return {
        "repo_id": repo_id,
        "template_id": template_id,
        "workspace_auth_token": workspace_auth_token,
        "template_path": template_path,
        "blocks": [],
        "paragraphs": [],
        "doc_blocks": [],
        "generated_images": {},
        "total_blocks": 0,
        "current_paragraph_index": 0,
        "total_paragraphs": 0,
        "status": GenerationStatus.PENDING.value,
        "message": "等待开始...",
        "error": None,
        "document_id": None,
        "title": None,
        "selected_strategy": None,
        "estimated_tokens": 0,
        "current_node": None,
        "progress": None,
        "__progress_reporter": None,
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
    }
