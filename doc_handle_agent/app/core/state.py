"""Agent状态定义."""

from enum import Enum
from typing import Dict, List, Optional, TypedDict, Union


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


class ListTemplateChild:
    """列表模板下的子段落定义.

    用于描述 list=true 时，每个列表项下的子段落结构。
    子段落可以是静态的（保持原样）或动态的（需要生成）。
    """

    def __init__(
        self,
        id: str,
        static_prefix: str,  # 静态前缀，如 "1.1 标识"
        template_block: Optional["ContentBlock"] = None,  # 动态模板块，None表示纯静态
    ):
        """初始化列表子段落.

        Args:
            id: 子段落ID
            static_prefix: 静态前缀文本
            template_block: 模板块（动态段落），None表示纯静态段落
        """
        self.id = id
        self.static_prefix = static_prefix
        self.template_block = template_block

    def to_dict(self) -> Dict:
        """转换为字典."""
        result = {
            "id": self.id,
            "static_prefix": self.static_prefix,
        }
        if self.template_block:
            result["template_block"] = self.template_block.to_dict()
        return result


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
        list_children: Optional[List[ListTemplateChild]] = None,  # list=true时的子段落定义
        parent_list_id: Optional[str] = None,  # 所属列表ID（当这是列表项下的子内容时）
        list_index: Optional[int] = None,  # 在列表项中的索引
    ):
        """初始化内容块.

        Args:
            id: 唯一标识
            type: 内容块类型
            prompt: LLM生成提示词
            is_list: 是否生成列表（仅headline类型支持）
            min_length: 最小字数限制
            max_length: 最大字数限制
            original_text: 原始标记文本
            list_children: 子段落定义列表（当is_list=true时）
            parent_list_id: 父列表ID（当这是列表项的子内容时）
            list_index: 在列表项中的索引（当这是列表项的子内容时）
        """
        self.id = id
        self.type = type
        self.prompt = prompt
        self.is_list = is_list
        self.min_length = min_length
        self.max_length = max_length
        self.original_text = original_text
        self.list_children = list_children
        self.parent_list_id = parent_list_id
        self.list_index = list_index

    def to_dict(self) -> Dict:
        """转换为字典."""
        result = {
            "id": self.id,
            "type": self.type.value,
            "prompt": self.prompt,
            "is_list": self.is_list,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "original_text": self.original_text,
        }
        if self.list_children:
            result["list_children"] = [child.to_dict() for child in self.list_children]
        if self.parent_list_id:
            result["parent_list_id"] = self.parent_list_id
        if self.list_index is not None:
            result["list_index"] = self.list_index
        return result

    def __repr__(self) -> str:
        return f"ContentBlock(id={self.id}, type={self.type.value}, prompt={self.prompt[:30]}..., is_list={self.is_list})"


class ListItemContent:
    """列表项内容 - 存储一个列表项及其子段落生成结果."""

    def __init__(
        self,
        headline: str,  # 列表项标题（如"用户管理"）
        child_contents: Dict[str, str],  # 子段落生成结果 {child_id: generated_content}
    ):
        """初始化列表项内容.

        Args:
            headline: 列表项标题
            child_contents: 子段落生成结果字典
        """
        self.headline = headline
        self.child_contents = child_contents

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "headline": self.headline,
            "child_contents": self.child_contents,
        }


class ListBlockResult:
    """列表块生成结果."""

    def __init__(
        self,
        items: List[ListItemContent],
        list_children_template: List[ListTemplateChild],  # 子段落模板定义
    ):
        """初始化列表块结果.

        Args:
            items: 列表项内容列表
            list_children_template: 子段落模板定义（用于重建结构）
        """
        self.items = items
        self.list_children_template = list_children_template

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "items": [item.to_dict() for item in self.items],
            "list_children_template": [child.to_dict() for child in self.list_children_template],
        }


class AgentState(TypedDict):
    """Agent工作流状态."""

    # 输入参数
    repo_id: str
    template_path: str
    output_path: str

    # 解析结果
    content_blocks: List[ContentBlock]

    # 生成结果
    # - 普通块: Dict[str, str]
    # - 列表块: Dict[str, ListBlockResult]
    generated_contents: Dict[str, Union[str, ListBlockResult]]

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
