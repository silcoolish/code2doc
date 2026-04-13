"""Agent状态定义."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, TypedDict, Union


class ParagraphType(str, Enum):
    """段落类型."""

    TEXT = "text"  # 正文
    HEADLINE = "headline"  # 标题


class GenerationStatus(str, Enum):
    """生成状态."""

    PENDING = "pending"
    PARSING = "parsing"
    GENERATING = "generating"
    BUILDING = "building"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StaticParagraph:
    """静态段落.

    表示模板中的静态段落（非模板），包含文本内容和可能的子段落。
    """

    id: str  # 唯一标识
    content: str  # 文本内容
    style_name: str  # 段落样式名称
    is_heading: bool  # 是否为标题
    children: List[Union["StaticParagraph", "TemplateParagraph"]] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """转换为字典."""
        result = {
            "id": self.id,
            "content": self.content,
            "style_name": self.style_name,
            "is_heading": self.is_heading,
        }
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result

    def __repr__(self) -> str:
        return f"StaticParagraph(id={self.id}, text={self.content[:30]}...)"


@dataclass
class TemplateParagraph:
    """模板段落.

    表示模板中的一个段落，可以是静态的或模板的。
    当 is_list=True 或 is_heading=True 时，children 包含所有子段落（静态或模板）。
    """

    id: str  # 唯一标识
    is_template: bool  # 是否是模板段落
    text: str  # 原始文本内容
    style_name: str  # 段落样式名称
    is_heading: bool  # 是否为标题

    # 模板属性（仅当 is_template=True 时有效）
    prompt: Optional[str] = None  # 生成提示词
    is_list: bool = False  # 是否生成列表
    min_length: Optional[int] = None  # 最小长度限制
    max_length: Optional[int] = None  # 最大长度限制
    img: Optional[str] = None  # 图片获取提示词（用于搜索并下载流程图）
    example: Optional[str] = None  # 内容生成参考示例

    # 子段落（当 is_list=True 或 is_heading=True 时有效）
    # 包含所有子段落，无论静态还是模板
    children: List[Union[StaticParagraph, "TemplateParagraph"]] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """转换为字典."""
        result = {
            "id": self.id,
            "is_template": self.is_template,
            "text": self.text,
            "style_name": self.style_name,
            "is_heading": self.is_heading,
        }

        if self.is_template:
            result["prompt"] = self.prompt
            result["is_list"] = self.is_list
            if self.min_length is not None:
                result["min_length"] = self.min_length
            if self.max_length is not None:
                result["max_length"] = self.max_length
            if self.img is not None:
                result["img"] = self.img
            if self.example is not None:
                result["example"] = self.example

        if self.children:
            result["children"] = [child.to_dict() for child in self.children]

        return result

    def __repr__(self) -> str:
        if self.is_template:
            return f"TemplateParagraph(id={self.id}, template=True, prompt={self.prompt[:30] if self.prompt else ''}..., is_list={self.is_list})"
        return f"TemplateParagraph(id={self.id}, template=False, text={self.text[:30]}...)"


@dataclass
class ImageInfo:
    """图片信息.

    存储下载的图片文件路径信息（图片保存在临时目录）。
    """

    image_id: str  # 图片唯一标识
    image_path: Optional[str] = None  # 图片文件路径（临时目录）
    image_format: str = "png"  # 图片格式（如 png, jpg）
    method_id: Optional[str] = None  # 关联的方法节点ID
    method_name: Optional[str] = None  # 方法名称

    def to_dict(self) -> Dict:
        """转换为字典."""
        return {
            "image_id": self.image_id,
            "image_path": self.image_path,
            "image_format": self.image_format,
            "method_id": self.method_id,
            "method_name": self.method_name,
        }


@dataclass
class GeneratedContentResult:
    """生成内容结果.

    存储段落生成的内容、层级结构以及关联的图片信息。
    用于表示单个段落（标题或正文）的生成结果。
    """

    is_heading: bool  # 是否为标题段落
    content: str  # 生成的文本内容
    children: List["GeneratedContentResult"] = field(default_factory=list)  # 子段落列表
    images: List[ImageInfo] = field(default_factory=list)  # 关联的图片列表（只有正文段落才会有）
    style_name: Optional[str] = None  # 原始段落样式名称（用于保留静态段落的样式）

    def to_dict(self) -> Dict:
        """转换为字典."""
        result = {
            "is_heading": self.is_heading,
            "content": self.content,
        }
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        if self.images:
            result["images"] = [img.to_dict() for img in self.images]
        if self.style_name:
            result["style_name"] = self.style_name
        return result

    @property
    def is_content(self) -> bool:
        """是否为正文段落（非标题且有实际内容）."""
        return not self.is_heading and not self.children


@dataclass
class ListItemResult:
    """列表项生成结果.

    存储一个列表项的生成结果，包括列表项本身的标题和子段落的生成内容。
    """

    headline: str  # 列表项标题
    # 子段落生成结果 {child_id: generated_content}
    # 对于静态子段落，值为原始文本
    # 对于模板子段落，值为 str 或 ListParagraphResult（支持嵌套列表）
    child_contents: Dict[str, Union[str, "ListParagraphResult"]] = field(default_factory=dict)
    images: List[ImageInfo] = field(default_factory=list)  # 关联的图片列表
    # 子段落图片 {child_id: 图片列表}，用于存储子段落生成的图片
    child_images: Dict[str, List["ImageInfo"]] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """转换为字典."""
        result = {
            "headline": self.headline,
        }
        # 处理可能包含 ListParagraphResult 的 child_contents
        serializable_contents = {}
        for child_id, content in self.child_contents.items():
            if isinstance(content, ListParagraphResult):
                serializable_contents[child_id] = content.to_dict()
            else:
                serializable_contents[child_id] = content
        result["child_contents"] = serializable_contents
        if self.images:
            result["images"] = [img.to_dict() for img in self.images]
        # 序列化子段落图片
        if self.child_images:
            serializable_child_images = {}
            for child_id, images in self.child_images.items():
                serializable_child_images[child_id] = [img.to_dict() for img in images]
            result["child_images"] = serializable_child_images
        return result


@dataclass
class ListParagraphResult:
    """列表模板段落的生成结果."""

    items: List[ListItemResult]  # 列表项结果
    # 子段落模板定义（用于重建结构）
    children_template: List[Union[StaticParagraph, TemplateParagraph]] = field(default_factory=list)
    images: List[ImageInfo] = field(default_factory=list)  # 关联的图片列表

    def to_dict(self) -> Dict:
        """转换为字典."""
        result = {
            "items": [item.to_dict() for item in self.items],
            "children_template": [child.to_dict() for child in self.children_template],
        }
        if self.images:
            result["images"] = [img.to_dict() for img in self.images]
        return result


class AgentState(TypedDict):
    """Agent工作流状态."""

    # 输入参数
    repo_id: str
    template_path: str
    output_path: str

    # 解析结果 - 模板段落列表
    paragraphs: List[TemplateParagraph]

    # 生成结果
    # {段落ID: 生成结果列表}
    # 对于列表段落，会有多个结果（每个列表项一个）
    # 对于单一段落，只有一个结果
    generated_contents: Dict[str, List[GeneratedContentResult]]

    # 图片信息
    # {段落ID: 图片信息列表}
    generated_images: Dict[str, List[ImageInfo]]

    # 进度
    current_paragraph_index: int
    total_paragraphs: int
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
        "paragraphs": [],
        "generated_contents": {},
        "generated_images": {},
        "current_paragraph_index": 0,
        "total_paragraphs": 0,
        "status": GenerationStatus.PENDING.value,
        "message": "等待开始...",
        "error": None,
    }


# 兼容性导出（保留旧名称以兼容现有代码，但指向新类型）
ContentBlock = TemplateParagraph
ContentBlockType = ParagraphType
ListBlockResult = ListParagraphResult
ListItemContent = ListItemResult
