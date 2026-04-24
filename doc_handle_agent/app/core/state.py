"""Agent状态定义."""

from typing import Dict, List, Optional, TypedDict

from app.domain.model import (
    DocumentBlock,
    GenerationStatus,
    ImageInfo,
    TemplateBlock,
)

__all__ = [
    "GenerationStatus",
    "TemplateBlock",
    "ImageInfo",
    "DocumentBlock",
    "AgentState",
    "create_initial_state",
]


class AgentState(TypedDict):
    """Agent工作流状态."""

    # 输入参数
    repo_id: str
    template_id: str  # 模板ID（替代原来的template_path）

    # 解析结果 - 模板block列表（新结构）
    blocks: List[TemplateBlock]

    # 生成结果
    # {block ID: 生成结果列表}
    # 对于列表block，会有多个结果（每个列表项一个）
    # 对于单一block，只有一个结果
    generated_contents: Dict[str, List[DocumentBlock]]

    # 图片信息
    # {block ID: 图片信息列表}
    generated_images: Dict[str, List[ImageInfo]]

    # 进度
    current_block_index: int  # 当前block索引
    total_blocks: int  # 总block数
    status: str
    message: str

    # 错误信息
    error: Optional[str]

    # 生成的文档ID
    document_id: Optional[str]

    # 策略选择结果
    selected_strategy: Optional[str]  # 选中的策略名称
    estimated_tokens: int  # 预估token数

    # 向后兼容的字段
    template_path: str
    output_path: str
    paragraphs: List  # 旧字段，保留兼容
    current_paragraph_index: int  # 旧字段，保留兼容
    total_paragraphs: int  # 旧字段，保留兼容


def create_initial_state(
    repo_id: str,
    template_id: str,
    template_path: str = "",
    output_path: str = "",
) -> AgentState:
    """创建初始状态.

    Args:
        repo_id: 仓库ID
        template_id: 模板ID
        template_path: 模板路径（保留向后兼容）
        output_path: 输出路径（保留向后兼容）

    Returns:
        初始Agent状态
    """
    return {
        "repo_id": repo_id,
        "template_id": template_id,
        "template_path": template_path,
        "output_path": output_path,
        "blocks": [],
        "paragraphs": [],
        "generated_contents": {},
        "generated_images": {},
        "current_block_index": 0,
        "total_blocks": 0,
        "current_paragraph_index": 0,
        "total_paragraphs": 0,
        "status": GenerationStatus.PENDING.value,
        "message": "等待开始...",
        "error": None,
        "document_id": None,
        "selected_strategy": None,
        "estimated_tokens": 0,
    }
