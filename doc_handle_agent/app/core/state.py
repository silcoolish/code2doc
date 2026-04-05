"""Agent状态定义."""

from enum import Enum
from typing import Dict, List, Optional, TypedDict


class ContentBlockType(str, Enum):
    """内容块类型."""

    TEXT = "text"
    HEADLINE = "headline"


class GenerationStatus(str, Enum):
    """生成状态."""

    PENDING = "pending"
    PARSING = "parsing"
    GENERATING = "generating"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"


class ContentBlock:
    """内容块数据类."""

    def __init__(
        self,
        id: str,
        type: ContentBlockType,
        prompt: str,
        is_list: bool = False,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        original_text: str = "",
    ):
        """初始化内容块.

        Args:
            id: 唯一标识 (段落索引)
            type: 内容块类型
            prompt: LLM生成提示词
            is_list: 是否生成列表
            min_length: 最小长度限制
            max_length: 最大长度限制
            original_text: 原始标记文本
        """
        self.id = id
        self.type = type
        self.prompt = prompt
        self.is_list = is_list
        self.min_length = min_length
        self.max_length = max_length
        self.original_text = original_text

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "id": self.id,
            "type": self.type.value,
            "prompt": self.prompt,
            "is_list": self.is_list,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "original_text": self.original_text,
        }

    def __repr__(self) -> str:
        return f"ContentBlock(id={self.id}, type={self.type.value}, prompt={self.prompt[:30]}...)"


class AgentState(TypedDict):
    """Agent工作流状态."""

    # 输入参数
    repo_id: str
    template_path: str
    output_path: str

    # 解析结果
    content_blocks: List[ContentBlock]

    # 生成结果
    generated_contents: Dict[str, str]

    # 进度
    current_block_index: int
    total_blocks: int
    status: str
    message: str

    # 错误信息
    error: Optional[str]


def create_initial_state(
    repo_id: str,
    template_path: str,
    output_path: str,
) -> AgentState:
    """创建初始状态.

    Args:
        repo_id: 仓库ID
        template_path: 模板路径
        output_path: 输出路径

    Returns:
        初始Agent状态
    """
    return {
        "repo_id": repo_id,
        "template_path": template_path,
        "output_path": output_path,
        "content_blocks": [],
        "generated_contents": {},
        "current_block_index": 0,
        "total_blocks": 0,
        "status": GenerationStatus.PENDING.value,
        "message": "等待开始...",
        "error": None,
    }
